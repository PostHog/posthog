"""Take a retired field out of the ORM while its column stays in Postgres.

Vendored from django-deprecate-fields 0.2.3, Copyright 3YOURMIND GmbH, Apache License 2.0.
Upstream: https://github.com/3YOURMIND/django-deprecate-fields

Vendored so the list of migration commands below lives in this repo, where our own commands
can be added to it.
"""

import sys
import logging
import warnings

logger = logging.getLogger(__name__)

# Under these the real field must stay on the model, or makemigrations sees a field that is
# missing from model state and offers a RemoveField that would drop the column.
_MIGRATION_COMMANDS = frozenset(
    {
        "makemigrations",
        "migrate",
        "showmigrations",
        "sqlmigrate",
        "squashmigrations",
        "analyze_migration_risk",
    }
)


class FieldDeprecatedError(Exception):
    pass


def in_migration_context() -> bool:
    """True when this process runs a command that reads or writes Django migration state.

    Only the subcommand counts, which is sys.argv[1] for both manage.py and django-admin.
    Matching any argv token instead would let "pytest -k migrate" put every deprecated field
    back on its model for the whole run.
    """
    return len(sys.argv) > 1 and sys.argv[1] in _MIGRATION_COMMANDS


class DeprecatedField:
    """Stands in for a field whose column is still in the database.

    Django names every concrete field in every SELECT and INSERT it writes. A plain
    descriptor is not a concrete field, so the column leaves all generated SQL while the
    column itself stays untouched. Use deprecate_field() instead of this class directly.
    """

    def __init__(self, raise_on_access: bool = False) -> None:
        self.raise_on_access = raise_on_access

    def _get_name(self, obj: object) -> str:
        for name, value in type(obj).__dict__.items():
            if value is self:
                return name
        return "<unknown>"

    def __get__(self, obj: object, objtype: type | None = None) -> object:
        if obj is None:
            return self
        self._report(f"accessing deprecated field {obj.__class__.__name__}.{self._get_name(obj)}")
        return None

    def __set__(self, obj: object, val: object) -> None:
        # The write is dropped on purpose: a descriptor is shared by every instance, so storing
        # the value here would leak it into every other row, and no column is left to hold it.
        self._report(f"writing to deprecated field {obj.__class__.__name__}.{self._get_name(obj)}")

    def _report(self, msg: str) -> None:
        if self.raise_on_access:
            raise FieldDeprecatedError(msg)
        warnings.warn(msg, DeprecationWarning, stacklevel=3)
        logger.warning(msg)


def deprecate_field(field_instance: object, raise_on_access: bool = False) -> object:
    """Hide a field from the ORM without touching its column.

    This is phase 1 of a column retirement, and on its own it is a complete and safe end
    state: the column keeps its data and any release can be rolled back to. Wrap the field,
    deploy, and stop there unless the column has to go.

    To finish the drop, one full deploy cycle later, delete the wrapped line, run
    makemigrations, and replace the generated RemoveField with untrack_field(). A following
    migration drops the column with RunSQL. The risk analyzer validates that shape on its own,
    by finding the state removal among the drop migration's ancestors.

    The field must already be null=True. Nothing writes the column once the field is hidden,
    so a NOT NULL column would reject every later insert. Declaring the nullability in the
    model keeps the ALTER TABLE it needs visible in review and scored by the risk analyzer.

    Args:
        field_instance: The field to hide, written exactly as it is today, and null=True.
        raise_on_access: Raise FieldDeprecatedError instead of logging a warning. Use it to
            prove no caller is left before the column is dropped.
    """
    if getattr(field_instance, "null", False) is not True:
        raise FieldDeprecatedError(
            "deprecate_field() needs a field that is already null=True, because nothing writes "
            "the column once the field is hidden. Set null=True on the field in the model, let "
            "makemigrations write the AlterField, and wrap it after that lands."
        )
    if in_migration_context():
        return field_instance
    return DeprecatedField(raise_on_access=raise_on_access)

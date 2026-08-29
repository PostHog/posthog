"""Errors raised while validating or compiling a check.

Plain exceptions, not DRF ``APIException``s: these are raised from Temporal activities as well as
from serializers, and the presentation layer is responsible for mapping them to a status code.
"""


class CheckConfigError(ValueError):
    """The check's config, column, or custom query is unusable for its type."""


class SubjectUnresolvableError(ValueError):
    """The subject a check targets no longer resolves in its owning product."""


class CheckEditConflict(ValueError):
    """An edit that cannot be committed as asked, addressed to the fields at fault.

    Carries ``code`` and ``fields`` so the presentation layer can render it beside the offending
    form fields instead of as a bare status code.
    """

    code = "check_edit_conflict"
    fields: tuple[str, ...] = ()


class DuplicateDefinitionError(CheckEditConflict):
    """Another active check on this subject already asserts exactly this."""

    code = "duplicate_definition"
    fields = ("config", "check_type", "column_name")

    def __init__(self, message: str = "A check with this definition already exists.") -> None:
        super().__init__(message)


class NameConflictError(CheckEditConflict):
    """Another check in the project already holds this name."""

    code = "name_conflict"
    fields = ("name",)

    def __init__(self, message: str = "A check with this name already exists.") -> None:
        super().__init__(message)

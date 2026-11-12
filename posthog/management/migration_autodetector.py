from django.db import models
from django.db.migrations.autodetector import MigrationAutodetector


class PostHogAutodetector(MigrationAutodetector):
    """Leave attributes that never reach the database out of the field comparison.

    The schema editor skips these attributes when it decides whether a column changes
    (Field.non_db_attrs), so an AlterField that changes only them runs no SQL. Django still
    writes that AlterField, and each one costs a migration file, a max_migration.txt conflict
    and a migration review. CreateModel and AddField still serialize the full field, and an
    AlterField for a real column change carries the current choices and help_text, so
    migration state catches up then.

    `default` stays compared: AlterField reads it from state to fill NULLs when a column
    becomes NOT NULL, and RunPython code that creates rows reads it from historical models.
    """

    IGNORED_FIELD_ATTRS = frozenset(
        {
            "blank",
            "choices",
            "editable",
            "error_messages",
            "help_text",
            "limit_choices_to",
            "validators",
            "verbose_name",
        }
    )

    def deep_deconstruct(self, obj):
        deconstructed = super().deep_deconstruct(obj)
        if not isinstance(obj, models.Field):
            return deconstructed
        # A field subclass that stores one of these attributes in the database removes it from
        # non_db_attrs, and the intersection then keeps comparing it.
        ignored = self.IGNORED_FIELD_ATTRS.intersection(obj.non_db_attrs)
        path, args, kwargs = deconstructed
        return path, args, {key: value for key, value in kwargs.items() if key not in ignored}

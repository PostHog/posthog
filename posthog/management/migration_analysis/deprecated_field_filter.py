import re


class DeprecatedFieldFilter:
    """
    Filters 'Remove field' operations for fields wrapped in deprecate_field().

    Django-deprecate-fields hides deprecated fields from model introspection unless
    'makemigrations' is in sys.argv. This causes false positives where deprecated
    fields appear as missing operations in makemigrations output.

    This filter introspects only the models that have field removals, checking if
    those specific fields are wrapped in deprecate_field(). Only deprecated field
    removals are filtered out - real missing migrations are preserved.

    If django-deprecate-fields is not installed, filtering is skipped entirely.
    """

    # Check if django-deprecate-fields is available
    _deprecated_field_class = None
    try:
        from django_deprecate_fields import DeprecatedField

        _deprecated_field_class = DeprecatedField
    except ImportError:
        pass

    @staticmethod
    def _collect_removal_models(lines: list[str]) -> set[str]:
        """
        Extract model names from 'Remove field' operations.

        Returns set of lowercase model names that have field removals.
        """
        removal_models = set()
        for line in lines:
            if match := re.match(r"\s*-\s*Remove field \w+ from (\w+)", line):
                removal_models.add(match.group(1).lower())
        return removal_models

    @staticmethod
    def _get_deprecated_fields_for_models(model_names: set[str]) -> set[tuple[str, str]]:
        """
        Get deprecated fields for specific models only.

        Returns set of (model_name, field_name) tuples for fields that are instances
        of DeprecatedField. Only checks models whose names are in model_names.
        """
        if DeprecatedFieldFilter._deprecated_field_class is None:
            return set()

        from django.apps import apps

        deprecated_fields = set()
        DeprecatedField = DeprecatedFieldFilter._deprecated_field_class

        for model in apps.get_models():
            model_name = model._meta.object_name.lower()
            if model_name not in model_names:
                continue  # Skip models we don't care about

            # Check this model for DeprecatedField instances
            for field_name, field_value in model.__dict__.items():
                if isinstance(field_value, DeprecatedField):
                    deprecated_fields.add((model_name, field_name))

        return deprecated_fields

    @staticmethod
    def _filter_lines(lines: list[str], deprecated_fields: set[tuple[str, str]]) -> str:
        """
        Filter lines, removing deprecated field removal operations.

        Preserves non-deprecated operations and removes app headers that have no
        migrations after filtering.
        """
        result_lines = []
        current_migration_file = None
        current_migration_ops = []

        def is_deprecated_removal(line: str) -> bool:
            """Check if a 'Remove field' line is for a deprecated field."""
            # Match: "    - Remove field field_name from ModelName"
            match = re.match(r"\s*-\s*Remove field (\w+) from (\w+)", line)
            if not match:
                return False

            field_name = match.group(1)
            model_name = match.group(2).lower()

            # Check if this field is deprecated
            return (model_name, field_name) in deprecated_fields

        def finalize_migration():
            """Add current migration to results if it has non-deprecated operations."""
            nonlocal current_migration_file, current_migration_ops
            if current_migration_file and current_migration_ops:
                # Filter out operations that are deprecated field removals
                kept_ops = [op for op in current_migration_ops if not is_deprecated_removal(op)]

                if kept_ops:
                    # Has non-deprecated operations - include migration
                    result_lines.append(current_migration_file)
                    result_lines.extend(kept_ops)

            current_migration_file = None
            current_migration_ops = []

        for line in lines:
            # Check if this is an app header (e.g., "Migrations for 'posthog':")
            if line.startswith("Migrations for '"):
                # Finalize previous migration
                finalize_migration()
                # Add app header (we'll remove it later if it has no migrations)
                result_lines.append(line)

            # Check if this is a migration file line (e.g., "  posthog/migrations/...")
            elif line.strip() and line.startswith("  ") and "/" in line and ".py" in line:
                # Finalize previous migration
                finalize_migration()
                # Start new migration
                current_migration_file = line
                current_migration_ops = []

            # Check if this is an operation line (e.g., "    - Remove field ...")
            elif line.strip().startswith("- "):
                current_migration_ops.append(line)

        # Don't forget the last migration
        finalize_migration()

        # Remove app headers that have no migrations following them
        final_output = []
        i = 0
        while i < len(result_lines):
            line = result_lines[i]
            if line.startswith("Migrations for '"):
                # Check if the next line is another app header or end of list
                if i + 1 < len(result_lines) and not result_lines[i + 1].startswith("Migrations for '"):
                    # Has content, keep it
                    final_output.append(line)
                # else: skip this app header
            else:
                final_output.append(line)
            i += 1

        return "\n".join(final_output)

    @staticmethod
    def filter_output(output: str) -> str:
        """
        Filter deprecated field removals from makemigrations output.

        Returns filtered output with deprecated field removals hidden, or empty string
        if all operations were deprecated field removals.

        If django-deprecate-fields is not installed, returns output unchanged.
        """
        if DeprecatedFieldFilter._deprecated_field_class is None:
            # Library not available, no filtering possible
            return output

        lines = output.split("\n")

        # First pass: collect model names that have "Remove field" operations
        removal_models = DeprecatedFieldFilter._collect_removal_models(lines)

        if not removal_models:
            # No removals to filter, return as-is
            return output

        # Only introspect models that have removals (performance optimization)
        deprecated_fields = DeprecatedFieldFilter._get_deprecated_fields_for_models(removal_models)

        if not deprecated_fields:
            # No deprecated fields found, return as-is
            return output

        # Second pass: filter lines using deprecated fields set
        return DeprecatedFieldFilter._filter_lines(lines, deprecated_fields)

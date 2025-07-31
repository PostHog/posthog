from typing import cast
from django.db import models


def get_changed_fields_local(before_update: models.Model) -> list[str]:
    """
    Get the fields that have changed on a model.
    This is a local function that does not use the database.
    """

    from posthog.models.activity_logging.activity_log import (
        ActivityScope,
        common_field_exclusions,
        field_exclusions,
        signal_exclusions,
    )

    model_name = cast(ActivityScope, before_update.__class__.__name__)
    signal_excluded_fields = signal_exclusions.get(model_name, [])
    all_excluded_fields = field_exclusions.get(model_name, []) + common_field_exclusions + signal_excluded_fields

    changed_fields = []
    for field in before_update._meta.get_fields():
        if not hasattr(field, "name") or field.name in all_excluded_fields:
            continue

        if hasattr(before_update, field.name) and hasattr(before_update, field.name):
            try:
                old_val = getattr(before_update, field.name, None)
                new_val = getattr(before_update, field.name, None)

                if old_val != new_val:
                    changed_fields.append(field.name)
            except Exception:
                # If we can't safely compare, assume it changed to be safe
                changed_fields.append(field.name)

    return changed_fields

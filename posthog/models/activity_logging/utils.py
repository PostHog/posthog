from typing import cast
from django.db import models
import structlog
import traceback

logger = structlog.get_logger(__name__)


def get_changed_fields_local(before_update: models.Model, after_update: models.Model) -> list[str]:
    """
    Get the fields that have changed on a model.
    This is a local-only function that does not use the database, for performance.
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

        if hasattr(before_update, field.name) and hasattr(after_update, field.name):
            try:
                old_val = getattr(before_update, field.name, None)
                new_val = getattr(after_update, field.name, None)

                if old_val != new_val:
                    changed_fields.append(field.name)
            except Exception:
                # If we can't safely compare, assume it changed to be safe
                logger.warning(
                    "Field comparison failed",
                    model_name=model_name,
                    field_name=field.name,
                    before_update=before_update,
                    after_update=after_update,
                    error=traceback.format_exc(),
                )

                changed_fields.append(field.name)

    return changed_fields

import traceback
from typing import TYPE_CHECKING, Any, Optional, cast

from django.db import models
from django.db.models import Q, QuerySet

import structlog
from asgiref.local import Local

if TYPE_CHECKING:
    from posthog.models.activity_logging.activity_log import ActivityLog

logger = structlog.get_logger(__name__)


class ActivityLoggingStorage:
    """
    Thread-safe storage for activity logging context using asgiref.local.
    """

    def __init__(self):
        self._local = Local()

    def set_user(self, user: Any) -> None:
        self._local.user = user

    def get_user(self) -> Optional[Any]:
        return getattr(self._local, "user", None)

    def clear_user(self) -> None:
        if hasattr(self._local, "user"):
            delattr(self._local, "user")

    def set_was_impersonated(self, was_impersonated: bool) -> None:
        self._local.was_impersonated = was_impersonated

    def get_was_impersonated(self) -> bool:
        return getattr(self._local, "was_impersonated", False)

    def clear_was_impersonated(self) -> None:
        if hasattr(self._local, "was_impersonated"):
            delattr(self._local, "was_impersonated")

    def clear_all(self) -> None:
        self.clear_user()
        self.clear_was_impersonated()


activity_storage = ActivityLoggingStorage()


class ActivityLogVisibilityManager:
    """
    Manages visibility restrictions for activity logs.

    Controls which activity logs can be seen by users and which should be
    filtered out from external destinations and user-facing interfaces.

    Configuration is defined in activity_log.py as `activity_visibility_restrictions`.
    """

    @classmethod
    def _get_restrictions(cls) -> list[dict[str, Any]]:
        from posthog.models.activity_logging.activity_log import activity_visibility_restrictions

        return activity_visibility_restrictions

    @classmethod
    def is_restricted(cls, instance: "ActivityLog", restrict_for_staff: bool = False) -> bool:
        for config in cls._get_restrictions():
            if not restrict_for_staff and config.get("allow_staff"):
                continue
            if instance.scope != config.get("scope"):
                continue
            if instance.activity not in config.get("activities", []):
                continue
            exclude_conditions = config.get("exclude_when", {})
            if not exclude_conditions or all(
                getattr(instance, field, None) == value for field, value in exclude_conditions.items()
            ):
                return True
        return False

    @classmethod
    def build_exclusion_query(cls, is_staff: bool = False) -> Q | None:
        """
        Build a Q object that excludes restricted activity logs.

        Returns None if no exclusions apply (e.g., staff user with allow_staff restrictions).
        """
        exclusion_queries: list[Q] = []

        for config in cls._get_restrictions():
            if config.get("allow_staff") and is_staff:
                continue

            scope = config.get("scope")
            activities = config.get("activities", [])
            exclude_conditions = config.get("exclude_when", {})

            query = Q(scope=scope) & Q(activity__in=activities)
            for field, value in exclude_conditions.items():
                query &= Q(**{field: value})
            exclusion_queries.append(query)

        if not exclusion_queries:
            return None

        combined = exclusion_queries[0]
        for q in exclusion_queries[1:]:
            combined |= q
        return combined

    @classmethod
    def apply_to_queryset(cls, queryset: QuerySet, is_staff: bool = False) -> QuerySet:
        exclusion_query = cls.build_exclusion_query(is_staff)
        if exclusion_query is not None:
            return queryset.exclude(exclusion_query)
        return queryset


activity_visibility_manager = ActivityLogVisibilityManager()


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

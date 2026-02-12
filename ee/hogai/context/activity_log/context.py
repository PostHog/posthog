import re
import json
from typing import Any, cast

from django.db.models import QuerySet

from posthog.api.advanced_activity_logs.utils import get_activity_log_lookback_restriction
from posthog.api.advanced_activity_logs.viewset import apply_organization_scoped_filter
from posthog.models import Team, User
from posthog.models.activity_logging.activity_log import (
    ActivityLog,
    ActivityScope,
    apply_activity_visibility_restrictions,
    field_name_overrides,
)
from posthog.sync import database_sync_to_async

from .prompts import (
    ACTIVITY_LOG_CONTEXT_TEMPLATE,
    ACTIVITY_LOG_ENTRY_TEMPLATE,
    ACTIVITY_LOG_NO_RESULTS,
    ACTIVITY_LOG_PAGINATION_END,
    ACTIVITY_LOG_PAGINATION_MORE,
)

MAX_VALUE_LENGTH = 200

# Keep in sync with SCOPE_DISPLAY_NAMES in frontend/src/lib/components/ActivityLog/humanizeActivity.tsx
SCOPE_DISPLAY_NAMES: dict[str, str] = {
    "AlertConfiguration": "Alert",
    "BatchExport": "Destination",
    "ExternalDataSource": "Source",
    "HogFunction": "Data pipeline",
    "PersonalAPIKey": "Personal API key",
    "LLMTrace": "LLM trace",
}


def humanize_scope(scope: str) -> str:
    display = SCOPE_DISPLAY_NAMES.get(scope)
    if display:
        return display
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", scope)


class ActivityLogContext:
    def __init__(
        self,
        team: Team,
        user: User,
    ):
        self._team = team
        self._user = user

    async def fetch_and_format(
        self,
        *,
        scope: str | None = None,
        activity: str | None = None,
        item_id: str | None = None,
        user_email: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> str:
        entries, total_count = await self._fetch_entries(
            scope=scope,
            activity=activity,
            item_id=item_id,
            user_email=user_email,
            limit=limit,
            offset=offset,
        )
        return self._format_entries(
            entries,
            scope=scope,
            user_email=user_email,
            total_count=total_count,
            offset=offset,
            limit=limit,
        )

    @database_sync_to_async
    def _fetch_entries(
        self,
        *,
        scope: str | None = None,
        activity: str | None = None,
        item_id: str | None = None,
        user_email: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[ActivityLog], int]:
        queryset: QuerySet[ActivityLog] = ActivityLog.objects.select_related("user").order_by("-created_at")

        queryset = apply_organization_scoped_filter(
            queryset,
            bool(self._team.receive_org_level_activity_logs),
            self._team.id,
            self._team.organization_id,
        )

        lookback_date = get_activity_log_lookback_restriction(self._team.organization)
        if lookback_date:
            queryset = queryset.filter(created_at__gte=lookback_date)

        queryset = apply_activity_visibility_restrictions(queryset, self._user)

        if scope:
            queryset = queryset.filter(scope=scope)
        if activity:
            queryset = queryset.filter(activity=activity)
        if item_id:
            queryset = queryset.filter(item_id=item_id)
        if user_email:
            queryset = queryset.filter(user__email=user_email)

        limit = min(max(limit, 1), 50)
        total_count = queryset.count()
        entries = list(queryset[offset : offset + limit])
        return entries, total_count

    def _format_entries(
        self,
        entries: list[ActivityLog],
        *,
        scope: str | None = None,
        user_email: str | None = None,
        total_count: int = 0,
        offset: int = 0,
        limit: int = 20,
    ) -> str:
        if not entries:
            return ACTIVITY_LOG_NO_RESULTS

        formatted_entries: list[str] = []
        for entry in entries:
            formatted_entries.append(self._format_single_entry(entry))

        scope_filter = f" for scope={scope}" if scope else ""
        user_filter = f" by {user_email}" if user_email else ""

        has_more = total_count > offset + limit

        if has_more:
            pagination_hint = ACTIVITY_LOG_PAGINATION_MORE.format(next_offset=offset + limit)
        else:
            pagination_hint = ACTIVITY_LOG_PAGINATION_END

        return ACTIVITY_LOG_CONTEXT_TEMPLATE.format(
            count=len(formatted_entries),
            total_count=total_count,
            offset_start=offset + 1,
            offset_end=offset + len(formatted_entries),
            scope_filter=scope_filter,
            user_filter=user_filter,
            entries="\n".join(formatted_entries),
            pagination_hint=pagination_hint,
        )

    def _format_single_entry(self, entry: ActivityLog) -> str:
        timestamp = entry.created_at.strftime("%Y-%m-%d %H:%M UTC")

        user_attribution = self._format_user_attribution(entry)
        item_name = self._extract_item_name(entry)
        changes = self._format_changes(entry)

        return ACTIVITY_LOG_ENTRY_TEMPLATE.format(
            timestamp=timestamp,
            scope=humanize_scope(entry.scope),
            activity=entry.activity,
            item_name=item_name,
            user_attribution=user_attribution,
            changes=changes,
        )

    def _format_user_attribution(self, entry: ActivityLog) -> str:
        if entry.is_system:
            return " | by System"
        if entry.user:
            name = entry.user.first_name or entry.user.email
            suffix = " (impersonated)" if entry.was_impersonated else ""
            return f" | by {name}{suffix}"
        return ""

    def _extract_item_name(self, entry: ActivityLog) -> str:
        detail = entry.detail
        if not detail or not isinstance(detail, dict):
            return entry.item_id or "(unknown)"

        name = detail.get("name")
        if name:
            return str(name)

        short_id = detail.get("short_id")
        if short_id:
            return str(short_id)

        return entry.item_id or "(unknown)"

    def _format_changes(self, entry: ActivityLog) -> str:
        detail = entry.detail
        if not detail or not isinstance(detail, dict):
            return ""

        changes_data = detail.get("changes")
        if not changes_data or not isinstance(changes_data, list):
            return ""

        scope = cast(ActivityScope, entry.scope)
        overrides = field_name_overrides.get(scope, {})

        change_lines: list[str] = []
        for change in changes_data:
            if not isinstance(change, dict):
                continue

            raw_field = change.get("field", "unknown")
            field = overrides.get(raw_field, raw_field)
            action = change.get("action", "changed")
            before = self._truncate_value(change.get("before"))
            after = self._truncate_value(change.get("after"))

            if action == "created":
                change_lines.append(f"  - {field}: set to {after}")
            elif action == "deleted":
                change_lines.append(f"  - {field}: removed (was {before})")
            else:
                change_lines.append(f"  - {field}: {before} -> {after}")

        if not change_lines:
            return ""
        return "\n" + "\n".join(change_lines)

    def _truncate_value(self, value: Any) -> str:
        if value is None:
            return "(none)"
        if isinstance(value, dict | list):
            text = json.dumps(value, default=str)
        else:
            text = str(value)

        if len(text) > MAX_VALUE_LENGTH:
            return text[:MAX_VALUE_LENGTH] + "..."
        return text

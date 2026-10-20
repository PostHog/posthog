from datetime import UTC, datetime

from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from posthog.dataclasses import frozen
from posthog.models.events_retention_config import (
    ConfiguredEventsRetention,
    configured_events_retention,
    describe_months_range,
    whole_month_cutoff,
)


@frozen
class _RetentionRow:
    retention: ConfiguredEventsRetention
    source: str
    allowed_range: str
    deletes_before: datetime | None


def _row(retention: ConfiguredEventsRetention, now: datetime) -> _RetentionRow:
    if retention.team_months is not None:
        source = "Team setting"
    elif retention.organization_default_months is not None:
        source = "Organization default"
    else:
        source = "Not set, events are kept"
    low, high = retention.organization_min_months, retention.organization_max_months
    months = retention.months
    return _RetentionRow(
        retention=retention,
        source=source,
        allowed_range=describe_months_range(low, high)
        if low is not None or high is not None
        else "any number of months",
        deletes_before=whole_month_cutoff(now, months) if months is not None else None,
    )


def events_retention_view(request: HttpRequest) -> HttpResponse:
    if not request.user.is_staff:
        raise PermissionDenied

    now = datetime.now(UTC)
    context = {
        "rows": [_row(retention, now) for retention in configured_events_retention()],
        "title": "Events retention",
        "has_view_permission": True,
        "site_title": admin.site.site_title,
        "site_header": admin.site.site_header,
        "site_url": admin.site.site_url,
        "has_permission": True,
    }
    return render(request, "admin/events_retention.html", context)

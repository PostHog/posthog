import logging
from datetime import UTC, datetime, timedelta

from django import forms
from django.conf import settings
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme

from posthog.hogql.escape_sql import escape_clickhouse_identifier

from posthog.clickhouse.client import sync_execute
from posthog.models.distinct_id_usage.sql import TABLE_BASE_NAME
from posthog.models.event_ingestion_restriction_config import EventIngestionRestrictionConfig, RestrictionType
from posthog.models.team.team import Team

logger = logging.getLogger(__name__)

QUERY_SETTINGS = {"max_execution_time": 30}


def _escaped_table() -> str:
    db = escape_clickhouse_identifier(settings.CLICKHOUSE_DATABASE)
    tbl = escape_clickhouse_identifier(TABLE_BASE_NAME)
    return f"{db}.{tbl}"


def _query_high_usage(
    dt_from: datetime, dt_to: datetime, threshold: int, min_events_threshold: int, distinct_id_min_events: int
) -> list[tuple]:
    table = _escaped_table()
    query = """
        WITH team_totals AS (
            SELECT team_id, sum(event_count) as total_events
            FROM {table}
            WHERE minute >= %(dt_from)s AND minute < %(dt_to)s
            GROUP BY team_id
            HAVING total_events >= %(min_events_threshold)s
        ),
        distinct_id_totals AS (
            SELECT team_id, distinct_id, sum(event_count) as event_count
            FROM {table}
            WHERE minute >= %(dt_from)s AND minute < %(dt_to)s
            GROUP BY team_id, distinct_id
        )
        SELECT d.team_id, d.distinct_id, d.event_count, t.total_events,
               round(d.event_count * 100.0 / t.total_events, 2) as percentage
        FROM distinct_id_totals d
        JOIN team_totals t ON d.team_id = t.team_id
        WHERE d.event_count * 100.0 / t.total_events >= %(threshold)s
          AND d.event_count >= %(distinct_id_min_events)s
        ORDER BY d.event_count DESC
        LIMIT 100
        """.format(table=table)
    return sync_execute(
        query,
        {
            "dt_from": dt_from,
            "dt_to": dt_to,
            "threshold": threshold,
            "min_events_threshold": min_events_threshold,
            "distinct_id_min_events": distinct_id_min_events,
        },
        settings=QUERY_SETTINGS,
    )


def _query_high_cardinality(dt_from: datetime, dt_to: datetime, threshold: int) -> list[tuple]:
    table = _escaped_table()
    query = """
        SELECT team_id, uniq(distinct_id) as distinct_id_count
        FROM {table}
        WHERE minute >= %(dt_from)s AND minute < %(dt_to)s
        GROUP BY team_id
        HAVING distinct_id_count >= %(threshold)s
        ORDER BY distinct_id_count DESC
        LIMIT 100
        """.format(table=table)
    return sync_execute(
        query,
        {
            "dt_from": dt_from,
            "dt_to": dt_to,
            "threshold": threshold,
        },
        settings=QUERY_SETTINGS,
    )


def _query_bursts(dt_from: datetime, dt_to: datetime, threshold: int) -> list[tuple]:
    table = _escaped_table()
    query = """
        SELECT team_id, distinct_id, minute, event_count
        FROM {table}
        WHERE minute >= %(dt_from)s AND minute < %(dt_to)s
          AND event_count >= %(threshold)s
        ORDER BY event_count DESC
        LIMIT 100
        """.format(table=table)
    return sync_execute(
        query,
        {
            "dt_from": dt_from,
            "dt_to": dt_to,
            "threshold": threshold,
        },
        settings=QUERY_SETTINGS,
    )


DATETIME_FORMAT = "%Y-%m-%dT%H:%M"


def _default_from():
    return (datetime.now(tz=UTC) - timedelta(hours=6)).strftime(DATETIME_FORMAT)


def _default_to():
    return datetime.now(tz=UTC).strftime(DATETIME_FORMAT)


class DistinctIdUsageForm(forms.Form):
    datetime_from = forms.DateTimeField(
        label="From",
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format=DATETIME_FORMAT),
        input_formats=[DATETIME_FORMAT],
    )
    datetime_to = forms.DateTimeField(
        label="To",
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format=DATETIME_FORMAT),
        input_formats=[DATETIME_FORMAT],
    )

    def clean(self):
        cleaned = super().clean()
        if cleaned is None:
            return cleaned
        dt_from = cleaned.get("datetime_from")
        dt_to = cleaned.get("datetime_to")
        if dt_from and dt_to:
            if dt_from >= dt_to:
                raise forms.ValidationError("'From' must be before 'To'.")
            if (dt_to - dt_from).days > 7:
                raise forms.ValidationError("Range cannot exceed 7 days (table TTL).")
        return cleaned

    high_usage_percentage_threshold = forms.IntegerField(
        initial=30,
        min_value=1,
        max_value=100,
        label="High usage % threshold",
        help_text="Percentage of team events from a single distinct_id",
    )
    high_usage_min_events_threshold = forms.IntegerField(
        initial=10_000,
        min_value=1,
        label="Min team events",
        help_text="Minimum total team events to qualify",
    )
    high_usage_distinct_id_min_events = forms.IntegerField(
        initial=100_000,
        min_value=1,
        label="Min distinct_id events",
        help_text="Minimum events from a distinct_id to trigger",
    )
    high_cardinality_threshold = forms.IntegerField(
        initial=1_000_000,
        min_value=1,
        label="High cardinality threshold",
        help_text="Unique distinct_ids per team",
    )
    burst_threshold = forms.IntegerField(
        initial=100_000,
        min_value=1,
        label="Burst threshold",
        help_text="Events per minute from a single (team, distinct_id)",
    )


def _handle_add_to_restriction(request) -> None:
    restriction_id = request.POST.get("restriction_id")
    distinct_id = request.POST.get("distinct_id")

    if not restriction_id or not distinct_id:
        messages.error(request, "Missing restriction_id or distinct_id.")
        return

    try:
        restriction = EventIngestionRestrictionConfig.objects.get(pk=restriction_id)
    except EventIngestionRestrictionConfig.DoesNotExist:
        messages.error(request, f"Restriction {restriction_id} not found.")
        return

    label = f"{restriction.get_restriction_type_display()} restriction for {restriction.token[:16]}…"
    if restriction.add_distinct_id(distinct_id):
        messages.success(request, f"Added distinct_id to {label}")
    else:
        messages.info(request, f"distinct_id already in {label}")


def _handle_create_or_update_restriction(request) -> None:
    token = request.POST.get("token")
    restriction_type = request.POST.get("restriction_type")
    distinct_id = request.POST.get("distinct_id")

    if not token or not restriction_type or not distinct_id:
        messages.error(request, "Missing token, restriction_type, or distinct_id.")
        return

    if restriction_type not in RestrictionType.values:
        messages.error(request, f"Invalid restriction type: {restriction_type}")
        return

    restriction, created, added = EventIngestionRestrictionConfig.add_distinct_id_for_token(
        token, restriction_type, distinct_id
    )
    label = restriction.get_restriction_type_display()
    if created:
        messages.success(request, f"Created {label} restriction for {token[:16]}…")
    elif added:
        messages.success(request, f"Added distinct_id to existing {label} restriction for {token[:16]}…")
    else:
        messages.info(request, f"distinct_id already in {label} restriction.")


def _handle_post_action(request) -> HttpResponseRedirect:
    action = request.POST.get("action")
    return_querystring = request.POST.get("return_querystring", "")
    redirect_url = reverse("distinct-id-usage")
    if return_querystring:
        candidate = f"{redirect_url}?{return_querystring}"
        if url_has_allowed_host_and_scheme(candidate, allowed_hosts={request.get_host()}):
            redirect_url = candidate

    if action == "add_to_restriction":
        _handle_add_to_restriction(request)
    elif action == "create_or_update_restriction":
        _handle_create_or_update_restriction(request)
    else:
        messages.error(request, f"Unknown action: {action}")

    return HttpResponseRedirect(redirect_url)


def distinct_id_usage_view(request):
    if not request.user.is_staff:
        raise PermissionDenied

    if request.method == "POST":
        return _handle_post_action(request)

    initial = {"datetime_from": _default_from(), "datetime_to": _default_to()}
    form = DistinctIdUsageForm(request.GET or None, initial=initial)

    high_usage_rows: list[dict] = []
    high_cardinality_rows: list[dict] = []
    burst_rows: list[dict] = []
    errors: list[str] = []
    queried = False

    if form.is_valid():
        queried = True
        dt_from = form.cleaned_data["datetime_from"]
        dt_to = form.cleaned_data["datetime_to"]

        high_usage_raw: list[tuple] = []
        high_cardinality_raw: list[tuple] = []
        burst_raw: list[tuple] = []

        try:
            high_usage_raw = _query_high_usage(
                dt_from,
                dt_to,
                threshold=form.cleaned_data["high_usage_percentage_threshold"],
                min_events_threshold=form.cleaned_data["high_usage_min_events_threshold"],
                distinct_id_min_events=form.cleaned_data["high_usage_distinct_id_min_events"],
            )
        except Exception as e:
            logger.exception("Distinct ID usage: high usage query failed")
            errors.append(f"High usage query failed: {e}")

        try:
            high_cardinality_raw = _query_high_cardinality(
                dt_from, dt_to, threshold=form.cleaned_data["high_cardinality_threshold"]
            )
        except Exception as e:
            logger.exception("Distinct ID usage: high cardinality query failed")
            errors.append(f"High cardinality query failed: {e}")

        try:
            burst_raw = _query_bursts(dt_from, dt_to, threshold=form.cleaned_data["burst_threshold"])
        except Exception as e:
            logger.exception("Distinct ID usage: burst query failed")
            errors.append(f"Burst query failed: {e}")

        # Batch-lookup team API tokens
        all_team_ids: set[int] = set()
        for row in high_usage_raw:
            all_team_ids.add(row[0])
        for row in high_cardinality_raw:
            all_team_ids.add(row[0])
        for row in burst_raw:
            all_team_ids.add(row[0])

        team_tokens: dict[int, str] = {}
        if all_team_ids:
            team_tokens = dict(Team.objects.filter(id__in=all_team_ids).values_list("id", "api_token"))

        # Fetch analytics pipeline restrictions indexed by token
        # Each token can have multiple restriction types (skip_person, drop_event, etc.)
        analytics_restrictions: dict[str, list[EventIngestionRestrictionConfig]] = {}
        if team_tokens:
            for r in EventIngestionRestrictionConfig.objects.filter(
                token__in=team_tokens.values(), pipelines__contains=["analytics"]
            ):
                analytics_restrictions.setdefault(r.token, []).append(r)

        def _build_restriction_info(token: str, distinct_id: str | None = None) -> dict[str, str | bool]:
            restrictions = analytics_restrictions.get(token, [])
            if not restrictions:
                return {"restriction_status": "none"}

            if distinct_id:
                for r in restrictions:
                    if not r.distinct_ids or distinct_id in r.distinct_ids:
                        edit_url = reverse("admin:posthog_eventingestionrestrictionconfig_change", args=[r.pk])
                        if not r.distinct_ids:
                            return {
                                "restriction_status": "covered_all",
                                "restriction_edit_url": edit_url,
                                "restriction_type": r.get_restriction_type_display(),
                            }
                        return {
                            "restriction_status": "covered",
                            "restriction_edit_url": edit_url,
                            "restriction_type": r.get_restriction_type_display(),
                        }
                first = restrictions[0]
                edit_url = reverse("admin:posthog_eventingestionrestrictionconfig_change", args=[first.pk])
                return {
                    "restriction_status": "not_covered",
                    "restriction_edit_url": edit_url,
                    "restriction_id": str(first.pk),
                    "restriction_type": first.get_restriction_type_display(),
                }

            # No distinct_id context (high cardinality)
            first = restrictions[0]
            edit_url = reverse("admin:posthog_eventingestionrestrictionconfig_change", args=[first.pk])
            return {
                "restriction_status": "exists",
                "restriction_edit_url": edit_url,
                "restriction_type": first.get_restriction_type_display(),
                "restriction_count": str(len(restrictions)),
            }

        for row in high_usage_raw:
            team_id, distinct_id, event_count, total_team_events, percentage = row
            token = team_tokens.get(team_id, "")
            high_usage_rows.append(
                {
                    "team_id": team_id,
                    "distinct_id": distinct_id,
                    "event_count": f"{event_count:,}",
                    "total_team_events": f"{total_team_events:,}",
                    "percentage": percentage,
                    "token": token,
                    **_build_restriction_info(token, distinct_id),
                }
            )

        for row in high_cardinality_raw:
            team_id, distinct_id_count = row
            token = team_tokens.get(team_id, "")
            high_cardinality_rows.append(
                {
                    "team_id": team_id,
                    "distinct_id_count": f"{distinct_id_count:,}",
                    "token": token,
                    **_build_restriction_info(token),
                }
            )

        for row in burst_raw:
            team_id, distinct_id, minute, event_count = row
            token = team_tokens.get(team_id, "")
            burst_rows.append(
                {
                    "team_id": team_id,
                    "distinct_id": distinct_id,
                    "minute": str(minute),
                    "event_count": f"{event_count:,}",
                    "token": token,
                    **_build_restriction_info(token, distinct_id),
                }
            )

    context = {
        **admin.site.each_context(request),
        "title": "Distinct ID usage",
        "form": form,
        "queried": queried,
        "high_usage_rows": high_usage_rows,
        "high_cardinality_rows": high_cardinality_rows,
        "burst_rows": burst_rows,
        "errors": errors,
        "return_querystring": request.GET.urlencode(),
    }
    return render(request, "admin/distinct_id_usage.html", context)

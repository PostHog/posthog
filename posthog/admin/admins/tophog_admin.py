import logging
from collections import OrderedDict, defaultdict
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse

from posthog.models.event_ingestion_restriction_config import EventIngestionRestrictionConfig
from posthog.models.team.team import Team
from posthog.models.tophog.queries import query_tophog_filter_options, query_tophog_metrics

logger = logging.getLogger(__name__)

# Maps tophog key fields to EventIngestionRestrictionConfig filter fields, used both for
# matching existing restrictions against a tophog entry and for prefilling the add form
RESTRICTION_FILTER_FIELDS = {
    "distinct_id": "distinct_ids",
    "session_id": "session_ids",
    "event_name": "event_names",
    "event_uuid": "event_uuids",
}

# Maps tophog pipeline names (INGESTION_PIPELINE deployment values) to
# EventIngestionRestrictionConfig pipeline values until the naming is unified
TOPHOG_TO_RESTRICTION_PIPELINE = {
    "analytics": "analytics",
    "sessionreplay": "session_recordings",
    "errortracking": "errortracking",
    "clientwarnings": "clientwarnings",
}

PRESETS = OrderedDict(
    [
        ("5m", 5),
        ("15m", 15),
        ("30m", 30),
        ("1h", 60),
        ("3h", 180),
        ("6h", 360),
        ("12h", 720),
        ("1d", 1440),
        ("7d", 10080),
        ("30d", 43200),
    ]
)


def _parse_time_range(request) -> tuple[str, str, datetime, datetime]:
    """Return (mode, selected_preset, date_from, date_to)."""
    raw_from = request.GET.get("date_from", "")
    raw_to = request.GET.get("date_to", "")

    if raw_from and raw_to:
        try:
            date_from = datetime.fromisoformat(raw_from).replace(tzinfo=UTC)
            date_to = datetime.fromisoformat(raw_to).replace(tzinfo=UTC)
            return "absolute", "", date_from, date_to
        except ValueError:
            pass

    preset_key = request.GET.get("preset", "5m")
    if preset_key not in PRESETS:
        preset_key = "5m"

    now = datetime.now(tz=UTC)
    date_from = now - timedelta(minutes=PRESETS[preset_key])
    return "preset", preset_key, date_from, now


def _format_key(key: dict[str, str]) -> str:
    return ", ".join(f"{k}: {v}" for k, v in key.items())


def _resolve_team_tokens(keys: list[dict[str, str]]) -> dict[str, str]:
    """Map team_id (as it appears in tophog keys) to the team's API token."""
    team_ids = {key["team_id"] for key in keys if key.get("team_id", "").isdigit()}
    if not team_ids:
        return {}
    teams = Team.objects.filter(id__in=[int(team_id) for team_id in team_ids]).values_list("id", "api_token")
    return {str(team_id): api_token for team_id, api_token in teams}


def _key_token(key: dict[str, str], tokens_by_team_id: dict[str, str]) -> str:
    token = key.get("token", "")
    if token and token != "unknown":
        return token
    return tokens_by_team_id.get(key.get("team_id", ""), "")


def _map_pipelines(tophog_pipelines: list[str]) -> list[str]:
    return sorted({TOPHOG_TO_RESTRICTION_PIPELINE[p] for p in tophog_pipelines if p in TOPHOG_TO_RESTRICTION_PIPELINE})


def _restrictions_page_url(token: str, key: dict[str, str], tophog_pipelines: list[str]) -> str:
    """Link to the restrictions page for a tophog entry, carrying the full key for search and prefill."""
    params = {"token": token, **{k: v for k, v in key.items() if k != "token"}}
    if tophog_pipelines:
        params["pipelines"] = ",".join(tophog_pipelines)
    return reverse("tophog-restrictions") + "?" + urlencode(params)


def _create_restriction_url(token: str, key: dict[str, str], restriction_pipelines: list[str]) -> str:
    """Link to the event ingestion restriction add form, prefilled from a tophog key."""
    params = {"token": token}
    for key_field, config_field in RESTRICTION_FILTER_FIELDS.items():
        value = key.get(key_field)
        if value:
            params[config_field] = value
    if restriction_pipelines:
        params["pipelines"] = ",".join(restriction_pipelines)
    return reverse("admin:posthog_eventingestionrestrictionconfig_add") + "?" + urlencode(params)


def _restriction_matches(
    restriction: EventIngestionRestrictionConfig, key: dict[str, str], restriction_pipelines: list[str]
) -> bool:
    """Whether an existing restriction already covers the tophog entry described by key and pipelines.

    Mirrors the ingestion matching semantics: an empty filter list matches everything,
    a non-empty list matches if it contains the entry's value (fields combine with AND).
    Key fields absent from the tophog entry don't disqualify a restriction.
    """
    if _extendable_fields(restriction, key):
        return False
    if restriction_pipelines and restriction.pipelines and not set(restriction_pipelines) & set(restriction.pipelines):
        return False
    return True


def _extendable_fields(restriction: EventIngestionRestrictionConfig, key: dict[str, str]) -> list[str]:
    """Filter fields whose configured values exclude the tophog entry's value.

    Only non-empty lists qualify: appending to an empty list would narrow a
    match-everything filter down to a single value instead of extending it.
    """
    extendable = []
    for key_field, config_field in RESTRICTION_FILTER_FIELDS.items():
        value = key.get(key_field)
        configured = getattr(restriction, config_field) or []
        if value and configured and value not in configured:
            extendable.append(config_field)
    return extendable


def _extend_restriction(restriction: EventIngestionRestrictionConfig, key: dict[str, str]) -> list[str]:
    """Append the tophog entry's key values to the restriction's filter lists; returns changed fields."""
    changed = _extendable_fields(restriction, key)
    for key_field, config_field in RESTRICTION_FILTER_FIELDS.items():
        if config_field in changed:
            setattr(restriction, config_field, [*getattr(restriction, config_field), key[key_field]])
    if changed:
        restriction.save()
    return changed


def tophog_dashboard_view(request):
    if not request.user.is_staff:
        raise PermissionDenied

    mode, selected_preset, date_from, date_to = _parse_time_range(request)

    # If mode=absolute is explicitly requested via toggle but no dates yet, keep preset values
    if request.GET.get("mode") == "absolute" and not (request.GET.get("date_from") and request.GET.get("date_to")):
        mode = "absolute"

    selected_pipeline = request.GET.get("pipeline", "")
    selected_lane = request.GET.get("lane", "")
    pipelines: list[str] = []
    lanes: list[str] = []
    metrics: dict[str, list[dict]] = defaultdict(list)
    error = ""

    try:
        pipelines, lanes = query_tophog_filter_options(date_from, date_to)

        rows = query_tophog_metrics(
            date_from,
            date_to,
            pipeline=selected_pipeline or None,
            lane=selected_lane or None,
        )

        tokens_by_team_id = _resolve_team_tokens([row["key"] for row in rows])

        for row in rows:
            table_name = f"{row['metric']} ({row['type']})"
            token = _key_token(row["key"], tokens_by_team_id)
            metrics[table_name].append(
                {
                    "key": _format_key(row["key"]),
                    "value": row["total"],
                    "count": row["obs"],
                    "pipeline": ", ".join(row["pipelines"]),
                    "lane": ", ".join(row["lanes"]),
                    "token": token,
                    "restrictions_url": (_restrictions_page_url(token, row["key"], row["pipelines"]) if token else ""),
                }
            )
    except Exception as e:
        logger.exception("TopHog dashboard query failed")
        error = str(e)

    # Build query string fragment for pipeline/lane filters (used in preset/mode links)
    filter_params = {}
    if selected_pipeline:
        filter_params["pipeline"] = selected_pipeline
    if selected_lane:
        filter_params["lane"] = selected_lane
    filter_qs = ("&" + urlencode(filter_params)) if filter_params else ""

    date_from_str = date_from.strftime("%Y-%m-%dT%H:%M")
    date_to_str = date_to.strftime("%Y-%m-%dT%H:%M")

    context = {
        **admin.site.each_context(request),
        "title": "TopHog Dashboard",
        "error": error,
        "metrics": dict(metrics),
        "pipelines": pipelines,
        "lanes": lanes,
        "selected_pipeline": selected_pipeline,
        "selected_lane": selected_lane,
        "presets": list(PRESETS.keys()),
        "selected_preset": selected_preset,
        "mode": mode,
        "date_from": date_from_str,
        "date_to": date_to_str,
        "base_url": request.path,
        "filter_qs": filter_qs,
    }
    return render(request, "admin/tophog.html", context)


def tophog_restrictions_view(request):
    if not request.user.is_staff:
        raise PermissionDenied

    token = request.GET.get("token", "")
    key = {k: v for k, v in request.GET.items() if k not in ("token", "pipelines") and v}
    tophog_pipelines = [p for p in request.GET.get("pipelines", "").split(",") if p]
    restriction_pipelines = _map_pipelines(tophog_pipelines)

    if request.method == "POST":
        restriction = EventIngestionRestrictionConfig.objects.filter(
            pk=request.POST.get("restriction_id"), token=token
        ).first()
        if restriction is None:
            messages.error(request, "Restriction not found for this token.")
        else:
            changed = _extend_restriction(restriction, key)
            if changed:
                messages.success(
                    request,
                    f"Extended {restriction.get_restriction_type_display()} restriction: {', '.join(changed)}.",
                )
            else:
                messages.info(request, "Nothing to add — restriction unchanged.")
        return HttpResponseRedirect(f"{request.path}?{request.GET.urlencode()}")

    restrictions = (
        EventIngestionRestrictionConfig.objects.filter(token=token).order_by("restriction_type") if token else []
    )
    entries = [
        {
            "restriction": restriction,
            "matches": _restriction_matches(restriction, key, restriction_pipelines),
            "extendable_fields": _extendable_fields(restriction, key),
            "edit_url": reverse("admin:posthog_eventingestionrestrictionconfig_change", args=[restriction.pk]),
        }
        for restriction in restrictions
    ]

    unmapped_pipelines = [p for p in tophog_pipelines if p not in TOPHOG_TO_RESTRICTION_PIPELINE]

    context = {
        **admin.site.each_context(request),
        "title": "TopHog Restrictions",
        "token": token,
        "key": key,
        "tophog_pipelines": tophog_pipelines,
        "restriction_pipelines": restriction_pipelines,
        "unmapped_pipelines": unmapped_pipelines,
        "entries": entries,
        "create_url": _create_restriction_url(token, key, restriction_pipelines) if token else "",
        "dashboard_url": reverse("tophog-dashboard"),
    }
    return render(request, "admin/tophog_restrictions.html", context)

"""Find where a property definition is referenced across saved PostHog objects.

Detection is structural, mirroring how cohort references are found: stored filter/query JSON
is matched on ``{"key": <name>, "type": <property type>}`` entries (plus insight
``query_metadata``, which also covers breakdowns and HogQL expressions). References inside
ad-hoc queries that were never saved cannot be found this way.
"""

import json
from collections import defaultdict
from typing import Any, Optional

from django.core.cache import cache
from django.db.models import Q, QuerySet

from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client import sync_execute
from posthog.hogql_queries.query_metadata import QueryPropertiesExtractor
from posthog.models import Team
from posthog.utils import get_safe_cache, relative_date_parse

from products.cdp.backend.models.hog_functions.hog_function import HogFunction
from products.cohorts.backend.models.cohort import Cohort
from products.experiments.backend.models.experiment import Experiment
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.product_analytics.backend.models.insight import Insight
from products.surveys.backend.models import Survey
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow

PROPERTY_USED_IN_PAGE_SIZE = 100

USAGE_COUNTS_CACHE_TTL_SECONDS = 5 * 60
PROFILE_PERCENTAGES_CACHE_TTL_SECONDS = 24 * 60 * 60
QUERY_USAGE_CACHE_TTL_SECONDS = 24 * 60 * 60

# jsonpath matching any nested filter entry referencing the property. Same shape as the
# cohort-reference detection in posthog/api/cohort.py.
PROPERTY_JSONPATH = """jsonb_path_exists({field}, '$.** ? (@.key == $name && @.type == $ptype)', %s::jsonb)"""


def used_in_block(page: list[dict], total: int) -> dict[str, Any]:
    """Build one ``{results, total, has_more}`` block of the used_in response."""
    return {"results": page, "total": total, "has_more": total > len(page)}


def truncate_used_in_queryset(qs: QuerySet) -> tuple[list[dict], int]:
    """Return up to PROPERTY_USED_IN_PAGE_SIZE rows plus the total count.

    Fetches one row past the cap so the common short-list case derives the total from the
    page itself; the expensive predicate only runs a second time (via ``count()``) when the
    cap is actually exceeded.
    """
    page = list(qs[: PROPERTY_USED_IN_PAGE_SIZE + 1])
    if len(page) <= PROPERTY_USED_IN_PAGE_SIZE:
        return page, len(page)
    return page[:PROPERTY_USED_IN_PAGE_SIZE], qs.count()


def _jsonpath_vars(name: str, property_type: str) -> str:
    return json.dumps({"name": name, "ptype": property_type})


def get_insights_using_property(team: Team, name: str, property_type: str) -> QuerySet[Insight]:
    """Insights referencing the property in their stored query.

    Prefers the extracted ``query_metadata.properties`` (covers breakdowns and HogQL
    expressions), with a structural jsonpath fallback for insights whose metadata predates
    property extraction. The LIKE guard short-circuits the recursive jsonpath for insights
    that don't mention the name at all.
    """
    return (
        # nosemgrep: python.django.security.audit.query-set-extra.avoid-query-set-extra (parameterized via params)
        Insight.objects.filter(team_id=team.id, deleted=False)
        .extra(
            where=[
                """query::text LIKE %s
                AND (
                    query_metadata @> %s::jsonb
                    OR jsonb_path_exists(query, '$.** ? (@.key == $name && @.type == $ptype)', %s::jsonb)
                )"""
            ],
            params=[
                f"%{name}%",
                json.dumps({"properties": [{"name": name, "type": property_type}]}),
                _jsonpath_vars(name, property_type),
            ],
        )
        .order_by("id")
    )


def get_cohorts_using_property(team: Team, name: str, property_type: str) -> QuerySet[Cohort]:
    return (
        # nosemgrep: python.django.security.audit.query-set-extra.avoid-query-set-extra (parameterized via params)
        Cohort.objects.filter(team__project_id=team.project_id, deleted=False)
        .extra(
            where=["filters::text LIKE %s AND " + PROPERTY_JSONPATH.format(field="filters")],
            params=[f"%{name}%", _jsonpath_vars(name, property_type)],
        )
        .order_by("id")
    )


def get_feature_flags_using_property(team: Team, name: str, property_type: str) -> QuerySet[FeatureFlag]:
    return (
        # nosemgrep: python.django.security.audit.query-set-extra.avoid-query-set-extra (parameterized via params)
        FeatureFlag.objects.filter(team__project_id=team.project_id, deleted=False)
        .extra(
            where=["filters::text LIKE %s AND " + PROPERTY_JSONPATH.format(field="filters")],
            params=[f"%{name}%", _jsonpath_vars(name, property_type)],
        )
        .order_by("id")
    )


def get_experiments_using_property(
    team: Team, name: str, property_type: str, matching_flags: QuerySet[FeatureFlag]
) -> QuerySet[Experiment]:
    """Experiments referencing the property via their feature flag or their metric queries."""
    metric_matches = (
        # nosemgrep: python.django.security.audit.query-set-extra.avoid-query-set-extra (parameterized via params)
        Experiment.objects.filter(team__project_id=team.project_id, deleted=False)
        .extra(
            where=[
                "("
                + PROPERTY_JSONPATH.format(field="metrics")
                + " OR "
                + PROPERTY_JSONPATH.format(field="secondary_metrics")
                + ")"
            ],
            params=[_jsonpath_vars(name, property_type), _jsonpath_vars(name, property_type)],
        )
        .values_list("id", flat=True)
    )
    return Experiment.objects.filter(
        Q(id__in=list(metric_matches)) | Q(feature_flag__in=matching_flags.values_list("id", flat=True)),
        team__project_id=team.project_id,
        deleted=False,
    ).order_by("id")


def get_surveys_using_property(team: Team, matching_flags: QuerySet[FeatureFlag]) -> QuerySet[Survey]:
    """Surveys reference person properties through their targeting and linked flags."""
    flag_ids = list(matching_flags.values_list("id", flat=True))
    return (
        Survey.objects.filter(team__project_id=team.project_id, archived=False)
        .filter(
            Q(linked_flag_id__in=flag_ids)
            | Q(targeting_flag_id__in=flag_ids)
            | Q(internal_targeting_flag_id__in=flag_ids)
        )
        .order_by("id")
    )


def get_hog_functions_using_property(team: Team, name: str, property_type: str) -> QuerySet[HogFunction]:
    return (
        # nosemgrep: python.django.security.audit.query-set-extra.avoid-query-set-extra (parameterized via params)
        HogFunction.objects.filter(team_id=team.id, deleted=False)
        .extra(
            where=["filters::text LIKE %s AND " + PROPERTY_JSONPATH.format(field="filters")],
            params=[f"%{name}%", _jsonpath_vars(name, property_type)],
        )
        .order_by("id")
    )


def get_hog_flows_using_property(team: Team, name: str, property_type: str) -> QuerySet[HogFlow]:
    return (
        # nosemgrep: python.django.security.audit.query-set-extra.avoid-query-set-extra (parameterized via params)
        HogFlow.objects.filter(team_id=team.id)
        .exclude(status=HogFlow.State.ARCHIVED)
        .extra(
            where=[
                "("
                + PROPERTY_JSONPATH.format(field="trigger")
                + " OR "
                + PROPERTY_JSONPATH.format(field="actions")
                + ")"
            ],
            params=[_jsonpath_vars(name, property_type), _jsonpath_vars(name, property_type)],
        )
        .order_by("id")
    )


def fetch_30day_property_queries(team: Team, property_name: str, property_type: str) -> int:
    """Total times the property appeared in an executed query over the last 30 days.

    Mirrors ``fetch_30day_event_queries``: sums the ``property_usage`` app metrics that the
    query runner logs from query metadata on each execution.
    """
    cache_key = f"property_definition:property_views_total:{team.pk}:{property_type}:{property_name}"
    cached_result = get_safe_cache(cache_key)
    if cached_result is not None:
        return cached_result

    clickhouse_kwargs: dict[str, Any] = {
        "team_id": team.pk,
        "app_source": "property_usage",
        "metric_name": "viewed",
        "instance_id": f"property:{property_type}:{property_name}",
        "after": relative_date_parse("30d", team.timezone_info).strftime("%Y-%m-%dT%H:%M:%S"),
    }

    clickhouse_query = """
        SELECT
            sum(count) as count
        FROM app_metrics2
        WHERE team_id = %(team_id)s
        AND app_source = %(app_source)s
        AND timestamp >= toDateTime64(%(after)s, 6)
        AND instance_id = %(instance_id)s
        AND metric_name = %(metric_name)s
    """

    results = sync_execute(clickhouse_query, clickhouse_kwargs)

    if not isinstance(results, list):
        raise ValueError("Unexpected results from ClickHouse")

    total = results[0][0] if results else 0

    cache.set(cache_key, total, timeout=QUERY_USAGE_CACHE_TTL_SECONDS)

    return total


def _count_json_field_references(
    rows: list[tuple[Any, ...]],
    property_type: str,
    counts: dict[str, dict[str, int]],
    resource: str,
    extractor: QueryPropertiesExtractor,
) -> dict[Any, set[str]]:
    """Count each row once per property name found in its JSON payloads.

    Returns the names matched per row id so callers can follow references through
    relations (flag -> experiment, flag -> survey).
    """
    names_by_row: dict[Any, set[str]] = {}
    for row_id, *json_fields in rows:
        names = {
            ref.name
            for field in json_fields
            if field
            for ref in extractor.extract_properties(field)
            if ref.type == property_type
        }
        if not names:
            continue
        names_by_row[row_id] = names
        for name in names:
            counts[name][resource] += 1
    return names_by_row


def get_property_usage_counts(
    team: Team, property_type: str, names: Optional[list[str]] = None
) -> dict[str, dict[str, int]]:
    """Per-property counts of saved objects referencing it, keyed by property name.

    One pass per object type: insights aggregate DB-side over the extracted
    ``query_metadata``; the other models are project-bounded, so their filter JSON is walked
    in Python with the same extractor that builds insight metadata.
    """
    counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    extractor = QueryPropertiesExtractor()

    insight_rows = (
        # nosemgrep: python.django.security.audit.query-set-extra.avoid-query-set-extra (parameterized via params)
        Insight.objects.filter(team_id=team.id, deleted=False)
        .exclude(query_metadata__isnull=True)
        .extra(where=["query_metadata::text LIKE %s"], params=["%properties%"])
        .values_list("id", "query_metadata")
    )
    for _insight_id, metadata in insight_rows:
        refs = (metadata or {}).get("properties") or []
        insight_names = {
            ref["name"]
            for ref in refs
            if isinstance(ref, dict) and ref.get("type") == property_type and ref.get("name")
        }
        for name in insight_names:
            counts[name]["insights"] += 1

    cohort_rows = list(
        Cohort.objects.filter(team__project_id=team.project_id, deleted=False).values_list("id", "filters")
    )
    _count_json_field_references(cohort_rows, property_type, counts, "cohorts", extractor)

    flag_rows = list(
        FeatureFlag.objects.filter(team__project_id=team.project_id, deleted=False).values_list("id", "filters")
    )
    flag_names_by_id = _count_json_field_references(flag_rows, property_type, counts, "feature_flags", extractor)

    experiment_rows = list(
        Experiment.objects.filter(team__project_id=team.project_id, deleted=False).values_list(
            "id", "metrics", "secondary_metrics"
        )
    )
    experiment_names_by_id = _count_json_field_references(
        experiment_rows, property_type, counts, "experiments", extractor
    )
    # Experiments also reference properties through their flag's targeting conditions.
    experiment_flags = Experiment.objects.filter(
        team__project_id=team.project_id, deleted=False, feature_flag_id__in=flag_names_by_id.keys()
    ).values_list("id", "feature_flag_id")
    for experiment_id, flag_id in experiment_flags:
        for name in flag_names_by_id[flag_id] - experiment_names_by_id.get(experiment_id, set()):
            counts[name]["experiments"] += 1

    survey_flags = Survey.objects.filter(team__project_id=team.project_id, archived=False).values_list(
        "id", "linked_flag_id", "targeting_flag_id", "internal_targeting_flag_id"
    )
    for _survey_id, *flag_ids in survey_flags:
        survey_names = set()
        for flag_id in flag_ids:
            survey_names |= flag_names_by_id.get(flag_id, set())
        for name in survey_names:
            counts[name]["surveys"] += 1

    hog_function_rows = list(HogFunction.objects.filter(team_id=team.id, deleted=False).values_list("id", "filters"))
    _count_json_field_references(hog_function_rows, property_type, counts, "hog_functions", extractor)

    hog_flow_rows = list(
        HogFlow.objects.filter(team_id=team.id)
        .exclude(status=HogFlow.State.ARCHIVED)
        .values_list("id", "trigger", "actions")
    )
    _count_json_field_references(hog_flow_rows, property_type, counts, "hog_flows", extractor)

    if names is not None:
        wanted = set(names)
        return {name: dict(resources) for name, resources in counts.items() if name in wanted}
    return {name: dict(resources) for name, resources in counts.items()}


def get_used_property_names(team: Team, property_type: str) -> set[str]:
    """Names of properties referenced by at least one saved object, cached briefly."""
    cache_key = f"property_definition:used_names:{team.pk}:{property_type}"
    cached_result = get_safe_cache(cache_key)
    if cached_result is not None:
        return cached_result

    used_names = set(get_property_usage_counts(team, property_type).keys())
    cache.set(cache_key, used_names, timeout=USAGE_COUNTS_CACHE_TTL_SECONDS)
    return used_names


def get_person_profile_percentages(team: Team) -> tuple[dict[str, float], int]:
    """Share of person profiles carrying each property, as {name: percent}, plus the total count.

    One aggregation over ``persons`` covers every property at once, so the result is cached
    per team and shared across table pages.
    """
    cache_key = f"property_definition:person_profile_percentages:{team.pk}"
    cached_result = get_safe_cache(cache_key)
    if cached_result is not None:
        return cached_result

    totals = execute_hogql_query(query="SELECT count() FROM persons", team=team)
    total_persons = int(totals.results[0][0]) if totals.results else 0

    percentages: dict[str, float] = {}
    if total_persons > 0:
        keys = execute_hogql_query(
            query="""
                SELECT key, count() AS persons_with_key
                FROM (SELECT arrayJoin(JSONExtractKeys(properties)) AS key FROM persons)
                GROUP BY key
            """,
            team=team,
        )
        percentages = {row[0]: round(100 * int(row[1]) / total_persons, 1) for row in keys.results or []}

    result = (percentages, total_persons)
    cache.set(cache_key, result, timeout=PROFILE_PERCENTAGES_CACHE_TTL_SECONDS)
    return result

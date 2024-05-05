from typing import Optional
from collections.abc import Callable

from django.utils.timezone import now
from statshog.defaults.django import statsd

from ee.clickhouse.queries.experiments.funnel_experiment_result import (
    ClickhouseFunnelExperimentResult,
)
from ee.clickhouse.queries.experiments.trend_experiment_result import (
    ClickhouseTrendExperimentResult,
)
from posthog.caching.insight_cache import update_cached_state
from posthog.clickhouse.query_tagging import tag_queries
from posthog.constants import INSIGHT_TRENDS
from posthog.models.experiment import Experiment
from posthog.models.filters.filter import Filter
from posthog.utils import generate_cache_key, get_safe_cache

EXPERIMENT_RESULTS_CACHE_DEFAULT_TTL = 60 * 60  # 1 hour


def calculate_experiment_results(experiment: Experiment, refresh: bool = False):
    # :TRICKY: Don't run any filter simplification on the experiment filter yet
    filter = Filter({**experiment.filters, "is_simplified": True}, team=experiment.team)

    exposure_filter_data = (experiment.parameters or {}).get("custom_exposure_filter")
    exposure_filter = None
    if exposure_filter_data:
        exposure_filter = Filter(data={**exposure_filter_data, "is_simplified": True}, team=experiment.team)

    if filter.insight == INSIGHT_TRENDS:
        calculate_func = lambda: ClickhouseTrendExperimentResult(
            filter,
            experiment.team,
            experiment.feature_flag,
            experiment.start_date,
            experiment.end_date,
            custom_exposure_filter=exposure_filter,
        ).get_results()
    else:
        calculate_func = lambda: ClickhouseFunnelExperimentResult(
            filter,
            experiment.team,
            experiment.feature_flag,
            experiment.start_date,
            experiment.end_date,
        ).get_results()

    return experiment_results_cached(
        experiment,
        "primary",
        filter,
        calculate_func,
        refresh=refresh,
        exposure_filter=exposure_filter,
    )


def experiment_results_cached(
    experiment: Experiment,
    results_type: str,
    filter: Filter,
    calculate_func: Callable,
    refresh: bool,
    exposure_filter: Optional[Filter] = None,
):
    cache_filter = filter.shallow_clone(
        {
            "date_from": experiment.start_date,
            "date_to": experiment.end_date if experiment.end_date else None,
        }
    )

    exposure_suffix = "" if not exposure_filter else f"_{exposure_filter.toJSON()}"

    cache_key = generate_cache_key(
        f"experiment_{results_type}_{cache_filter.toJSON()}_{experiment.team.pk}_{experiment.pk}{exposure_suffix}"
    )

    tag_queries(cache_key=cache_key)

    cached_result_package = get_safe_cache(cache_key)

    if cached_result_package and cached_result_package.get("result") and not refresh:
        cached_result_package["is_cached"] = True
        statsd.incr(
            "posthog_cached_function_cache_hit",
            tags={"route": "/projects/:id/experiments/:experiment_id/results"},
        )
        return cached_result_package

    statsd.incr(
        "posthog_cached_function_cache_miss",
        tags={"route": "/projects/:id/experiments/:experiment_id/results"},
    )

    result = calculate_func()

    timestamp = now()
    fresh_result_package = {"result": result, "last_refresh": now(), "is_cached": False}

    update_cached_state(
        experiment.team.pk,
        cache_key,
        timestamp,
        fresh_result_package,
        ttl=EXPERIMENT_RESULTS_CACHE_DEFAULT_TTL,
    )

    return fresh_result_package

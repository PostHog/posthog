from django.conf import settings
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
import structlog

from django.db.models import Q
from django.db import transaction

from posthog.models.cohort.cohort import Cohort, CohortOrEmpty
from posthog.models.feature_flag import FeatureFlag
from posthog.models.group_type_mapping import GroupTypeMapping
from posthog.models.team import Team
from posthog.storage.hypercache import HyperCache

logger = structlog.get_logger(__name__)

DATABASE_FOR_LOCAL_EVALUATION = (
    "default"
    if ("local_evaluation" not in settings.READ_REPLICA_OPT_IN or "replica" not in settings.DATABASES)  # noqa: F821
    else "replica"
)

flags_hypercache = HyperCache(
    namespace="feature_flags",
    value="flags_with_cohorts.json",
    load_fn=lambda key: _get_flags_response_for_local_evaluation(HyperCache.team_from_key(key), include_cohorts=True),
)

flags_without_cohorts_hypercache = HyperCache(
    namespace="feature_flags",
    value="flags_without_cohorts.json",
    load_fn=lambda key: _get_flags_response_for_local_evaluation(HyperCache.team_from_key(key), include_cohorts=False),
)


def get_flags_response_for_local_evaluation(team: Team, include_cohorts: bool) -> dict | None:
    return (
        flags_hypercache.get_from_cache(team)
        if include_cohorts
        else flags_without_cohorts_hypercache.get_from_cache(team)
    )


def update_flag_caches(team: Team):
    flags_hypercache.update_cache(team)
    flags_without_cohorts_hypercache.update_cache(team)


def clear_flag_caches(team: Team, kinds: list[str] | None = None):
    flags_hypercache.clear_cache(team, kinds=kinds)
    flags_without_cohorts_hypercache.clear_cache(team, kinds=kinds)


def _get_flags_for_local_evaluation(team: Team, include_cohorts: bool = True) -> tuple[list[FeatureFlag], dict]:
    """
    Get all feature flags for a team with conditional cohort handling for local evaluation.

    This method supports two different client integration patterns:

    Args:
        team: The team to get feature flags for.
        include_cohorts: Controls cohort handling strategy for client compatibility.

    Returns:
        tuple[list[FeatureFlag], dict]: (flags, cohorts_dict)

    Behavior based on include_cohorts:

    When include_cohorts=True (for smart clients):
        - Flag filters are kept unchanged (cohort references preserved)
        - Returns cohorts dict with cohort definitions for client-side evaluation
        - Client must evaluate cohort membership locally using provided cohort criteria

    When include_cohorts=False (for simple clients):
        - Flag filters are transformed (simple cohorts expanded to person properties)
        - Returns empty cohorts dict
        - Client only needs to evaluate simplified property-based filters
    """

    feature_flags = FeatureFlag.objects.db_manager(DATABASE_FOR_LOCAL_EVALUATION).filter(
        ~Q(is_remote_configuration=True),
        team__project_id=team.project_id,
        deleted=False,
    )

    cohorts = {}
    seen_cohorts_cache: dict[int, CohortOrEmpty] = {}

    try:
        seen_cohorts_cache = {
            cohort.pk: cohort
            for cohort in Cohort.objects.db_manager(DATABASE_FOR_LOCAL_EVALUATION).filter(
                team__project_id=team.project_id, deleted=False
            )
        }
    except Exception:
        logger.error("Error prefetching cohorts", exc_info=True)

    for feature_flag in feature_flags:
        try:
            filters = feature_flag.get_filters()

            # Capture cohort_ids BEFORE transformation to avoid losing cohort references
            cohort_ids = feature_flag.get_cohort_ids(
                using_database=DATABASE_FOR_LOCAL_EVALUATION,
                seen_cohorts_cache=seen_cohorts_cache,
            )

            # transform cohort filters to be evaluated locally, but only if include_cohorts is false
            if not include_cohorts and len(cohort_ids) == 1:
                feature_flag.filters = {
                    **filters,
                    "groups": feature_flag.transform_cohort_filters_for_easy_evaluation(
                        using_database=DATABASE_FOR_LOCAL_EVALUATION,
                        seen_cohorts_cache=seen_cohorts_cache,
                    ),
                }
            else:
                feature_flag.filters = filters

            # Only build cohorts when include_cohorts is True (matching send_cohorts behavior)
            if include_cohorts:
                for id in cohort_ids:
                    # don't duplicate queries for already added cohorts
                    if id not in cohorts:
                        if id in seen_cohorts_cache:
                            cohort = seen_cohorts_cache[id]
                        else:
                            cohort = (
                                Cohort.objects.db_manager(DATABASE_FOR_LOCAL_EVALUATION)
                                .filter(id=id, team__project_id=team.project_id, deleted=False)
                                .first()
                            )
                            seen_cohorts_cache[id] = cohort or ""

                        if cohort and not cohort.is_static:
                            try:
                                cohorts[str(cohort.pk)] = cohort.properties.to_dict()
                            except Exception:
                                logger.error(
                                    "Error processing cohort properties",
                                    extra={"cohort_id": id},
                                    exc_info=True,
                                )
                                continue

        except Exception:
            logger.error("Error processing feature flag", extra={"flag_id": feature_flag.pk}, exc_info=True)
            continue

    return feature_flags, cohorts


def _get_flags_response_for_local_evaluation(team: Team, include_cohorts: bool) -> dict:
    from posthog.api.feature_flag import MinimalFeatureFlagSerializer

    flags, cohorts = _get_flags_for_local_evaluation(team, include_cohorts)

    response_data = {
        "flags": [MinimalFeatureFlagSerializer(feature_flag, context={}).data for feature_flag in flags],
        "group_type_mapping": {
            str(row.group_type_index): row.group_type
            for row in GroupTypeMapping.objects.db_manager(DATABASE_FOR_LOCAL_EVALUATION).filter(
                project_id=team.project_id
            )
        },
        "cohorts": cohorts,
    }
    return response_data


# NOTE: All models that affect feature flag evaluation should have a signal to update the cache
# GroupTypeMapping excluded as it's primarily managed by Node.js plugin-server


@receiver(post_save, sender=FeatureFlag)
@receiver(post_delete, sender=FeatureFlag)
def feature_flag_changed(sender, instance: "FeatureFlag", **kwargs):
    from posthog.tasks.feature_flags import update_team_flags_cache

    # Defer task execution until after the transaction commits
    transaction.on_commit(lambda: update_team_flags_cache.delay(instance.team_id))


@receiver(post_save, sender=Cohort)
@receiver(post_delete, sender=Cohort)
def cohort_changed(sender, instance: "Cohort", **kwargs):
    from posthog.tasks.feature_flags import update_team_flags_cache

    transaction.on_commit(lambda: update_team_flags_cache.delay(instance.team_id))

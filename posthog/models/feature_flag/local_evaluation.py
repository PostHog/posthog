from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver
import structlog

from django.db.models import Q

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


def get_flags_response_for_local_evaluation(team: Team, include_cohorts: bool) -> dict:
    return (
        flags_hypercache.get_from_cache(team)
        if include_cohorts
        else flags_without_cohorts_hypercache.get_from_cache(team)
    )


def _get_flags_for_local_evaluation(team: Team):
    feature_flags = FeatureFlag.objects.db_manager(DATABASE_FOR_LOCAL_EVALUATION).filter(
        ~Q(is_remote_configuration=True),
        team__project_id=team.project_id,
        deleted=False,
    )

    return feature_flags


def _get_flags_with_cohorts_for_local_evaluation(team: Team) -> tuple[list[FeatureFlag], dict]:
    feature_flags = _get_flags_for_local_evaluation(team)

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
            # transform cohort filters to be evaluated locally
            if (
                len(
                    feature_flag.get_cohort_ids(
                        using_database=DATABASE_FOR_LOCAL_EVALUATION,
                        seen_cohorts_cache=seen_cohorts_cache,
                    )
                )
                == 1
            ):
                feature_flag.filters = {
                    **filters,
                    "groups": feature_flag.transform_cohort_filters_for_easy_evaluation(
                        using_database=DATABASE_FOR_LOCAL_EVALUATION,
                        seen_cohorts_cache=seen_cohorts_cache,
                    ),
                }
            else:
                feature_flag.filters = filters

            cohort_ids = feature_flag.get_cohort_ids(
                using_database=DATABASE_FOR_LOCAL_EVALUATION,
                seen_cohorts_cache=seen_cohorts_cache,
            )

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

    cohorts: dict[str, dict] = {}
    if include_cohorts:
        flags, cohorts = _get_flags_with_cohorts_for_local_evaluation(team)
    else:
        flags = _get_flags_for_local_evaluation(team)

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


def update_flag_caches(team: Team):
    flags_hypercache.update_cache(team)
    flags_without_cohorts_hypercache.update_cache(team)


# NOTE: All models that affect the cache should have a signal to update the cache


@receiver(post_save, sender=FeatureFlag)
def feature_flag_saved(sender, instance: "FeatureFlag", created, **kwargs):
    from posthog.tasks.feature_flags import update_team_flags_cache

    update_team_flags_cache.delay(instance.team_id)


@receiver(post_save, sender=Cohort)
def cohort_saved(sender, instance: "Cohort", created, **kwargs):
    from posthog.tasks.feature_flags import update_team_flags_cache

    update_team_flags_cache.delay(instance.team_id)

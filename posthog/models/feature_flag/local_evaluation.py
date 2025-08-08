import json
from django.core.cache import cache
from django.db.models.signals import post_save
from django.dispatch import receiver
from posthoganalytics import capture_exception
from prometheus_client import Counter
import structlog

from django.db.models import Q

from posthog.api.feature_flag import DATABASE_FOR_LOCAL_EVALUATION
from posthog.models.cohort.cohort import Cohort, CohortOrEmpty
from posthog.models.feature_flag import FeatureFlag
from posthog.models.group_type_mapping import GroupTypeMapping
from posthog.models.team import Team
from posthog.storage import object_storage
from posthog.storage.object_storage import ObjectStorageError

logger = structlog.get_logger(__name__)

CACHE_MISS_TIMEOUT = 60 * 60 * 24  # 1 day - it will be invalidated by the daily sync
CACHE_TIMEOUT = 60 * 60 * 24 * 30  # 30 days


CELERY_TASK_FLAGS_CACHE_SYNC = Counter(
    "posthog_flags_cache_sync",
    "Number of times the flags cache sync task has been run",
    labelnames=["result"],
)

FLAGS_CACHE_COUNTER = Counter(
    "posthog_flags_cache_via_cache",
    "Metric tracking whether a flags cache was fetched from cache or not",
    labelnames=["result"],
)


def cache_key(team_token: str, key: str) -> str:
    return f"feature_flags/local_evaluation/{team_token}/{key}"


class FeatureFlagLocalEvaluationCacheDoesNotExist(Exception):
    pass


class FeatureFlagLocalEvaluationCache:
    """
    This class is used for building and storing cached payloads of any feature flag elements that are used in high volume fault tolerant endpoints such as local evaluation.
    The methods are there for building the payloads but retrieval should ideally go only via the cached redis->s3 values.
    """

    @classmethod
    def get_flags_for_local_evaluation(cls, team: Team):
        feature_flags = FeatureFlag.objects.db_manager(DATABASE_FOR_LOCAL_EVALUATION).filter(
            ~Q(is_remote_configuration=True),
            team__project_id=team.project_id,
            deleted=False,
        )

        return feature_flags

    @classmethod
    def get_flags_with_cohorts_for_local_evaluation(cls, team: Team) -> tuple[list[FeatureFlag], dict]:
        feature_flags = cls.get_flags_for_local_evaluation(team)

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

    @classmethod
    def get_flags_response_for_local_evaluation(cls, team: Team, include_cohorts: bool) -> dict:
        from posthog.api.feature_flag import MinimalFeatureFlagSerializer

        cohorts = {}
        if include_cohorts:
            flags, cohorts = cls.get_flags_with_cohorts_for_local_evaluation(team)
        else:
            flags = cls.get_flags_for_local_evaluation(team)

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

    @classmethod
    def get_flags_response_for_local_evaluation_from_cache(cls, team: Team, include_cohorts: bool) -> dict:
        key = cache_key(team.api_token, "without_cohorts" if not include_cohorts else "with_cohorts")

        data = cache.get(key)
        if data == "404":
            FLAGS_CACHE_COUNTER.labels(result="hit_but_missing").inc()
            raise FeatureFlagLocalEvaluationCacheDoesNotExist()

        if data:
            FLAGS_CACHE_COUNTER.labels(result="hit_redis").inc()
            return json.loads(data)

        # Fallback to s3
        try:
            data = object_storage.read(key)
            if data:
                FLAGS_CACHE_COUNTER.labels(result="hit_s3").inc()
                return json.loads(data)
        except ObjectStorageError:
            pass

        # NOTE: This only applies to the django version - the dedicated service will rely entirely on the cache
        try:
            data = cls.get_flags_response_for_local_evaluation(team, include_cohorts)
            cache.set(key, json.dumps(data), timeout=CACHE_TIMEOUT)
            FLAGS_CACHE_COUNTER.labels(result="miss_but_success").inc()
            return data
        except FeatureFlagLocalEvaluationCacheDoesNotExist:
            cache.set(key, "404", timeout=CACHE_MISS_TIMEOUT)
            FLAGS_CACHE_COUNTER.labels(result="miss_but_missing").inc()
            raise

    @classmethod
    def update_cache(cls, team: Team):
        logger.info(f"Syncing flags cache for team {team.id}")

        try:
            CELERY_TASK_FLAGS_CACHE_SYNC.labels(result="success").inc()

            res_without_cohorts = json.dumps(cls.get_flags_response_for_local_evaluation(team, include_cohorts=False))
            res_with_cohorts = json.dumps(cls.get_flags_response_for_local_evaluation(team, include_cohorts=True))
            # Write files to S3
            object_storage.write(
                cache_key(team.api_token, "without_cohorts"),
                res_without_cohorts,
            )

            cache.set(cache_key(team.api_token, "without_cohorts"), res_without_cohorts, timeout=CACHE_TIMEOUT)

            object_storage.write(
                cache_key(team.api_token, "with_cohorts"),
                res_with_cohorts,
            )

            cache.set(cache_key(team.api_token, "with_cohorts"), res_with_cohorts, timeout=CACHE_TIMEOUT)

            CELERY_TASK_FLAGS_CACHE_SYNC.labels(result="success").inc()
        except Exception as e:
            capture_exception(e)
            logger.exception(f"Failed to sync flags cache for team {team.id}", exception=str(e))
            CELERY_TASK_FLAGS_CACHE_SYNC.labels(result="failure").inc()
            raise

        # FOLLOWUP: Also write to redis if we wan't django to be in charge of the hot cache.


# NOTE: All models that affect the cache should have a signal to update the cache


@receiver(post_save, sender=FeatureFlag)
def feature_flag_saved(sender, instance: "FeatureFlag", created, **kwargs):
    from posthog.tasks.feature_flags import update_team_flags_cache

    update_team_flags_cache.delay(instance.team_id)


@receiver(post_save, sender=Cohort)
def cohort_saved(sender, instance: "Cohort", created, **kwargs):
    from posthog.tasks.feature_flags import update_team_flags_cache

    update_team_flags_cache.delay(instance.team_id)

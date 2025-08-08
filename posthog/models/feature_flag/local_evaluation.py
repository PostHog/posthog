from typing
import structlog

from django.db.models import Q

from posthog.api.feature_flag import DATABASE_FOR_LOCAL_EVALUATION
from posthog.models.cohort.cohort import Cohort, CohortOrEmpty
from posthog.models.feature_flag import FeatureFlag
from posthog.models.group_type_mapping import GroupTypeMapping
from posthog.models.team import Team

logger = structlog.get_logger(__name__)


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
        except Exception as e:
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
                                .filter(id=id, team__project_id=self.project_id, deleted=False)
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

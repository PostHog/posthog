from typing import Optional

from rest_framework.exceptions import ValidationError

from posthog.client import sync_execute
from posthog.models.cohort import Cohort
from posthog.models.filters import Filter
from posthog.models.property import GroupTypeIndex
from posthog.models.team.team import Team


def get_user_blast_radius(
    team: Team,
    feature_flag_condition: dict,
    group_type_index: Optional[GroupTypeIndex] = None,
):
    from posthog.queries.person_query import PersonQuery

    # No rollout % calculations here, since it makes more sense to compute that on the frontend
    properties = feature_flag_condition.get("properties") or []

    if group_type_index is not None:
        try:
            from ee.clickhouse.queries.groups_join_query import GroupsJoinQuery
        except Exception:
            return 0, 0

        if len(properties) > 0:
            filter = Filter(data=feature_flag_condition, team=team)

            for property in filter.property_groups.flat:
                if property.group_type_index is None or (property.group_type_index != group_type_index):
                    raise ValidationError("Invalid group type index for feature flag condition.")

            groups_query, groups_query_params = GroupsJoinQuery(filter, team.id).get_filter_query(
                group_type_index=group_type_index
            )

            total_affected_count = sync_execute(
                f"""
                SELECT count(1) FROM (
                    {groups_query}
                )
            """,
                groups_query_params,
            )[0][0]
        else:
            total_affected_count = team.groups_seen_so_far(group_type_index)

        return total_affected_count, team.groups_seen_so_far(group_type_index)

    if len(properties) > 0:
        filter = Filter(data=feature_flag_condition, team=team)
        cohort_filters = []
        for property in filter.property_groups.flat:
            if property.type in ["cohort", "precalculated-cohort", "static-cohort"]:
                cohort_filters.append(property)

        target_cohort = None

        if len(cohort_filters) == 1:
            try:
                target_cohort = Cohort.objects.get(id=cohort_filters[0].value, team=team)
            except Cohort.DoesNotExist:
                pass
            finally:
                cohort_filters = []

        person_query, person_query_params = PersonQuery(
            filter, team.id, cohort=target_cohort, cohort_filters=cohort_filters
        ).get_query()

        total_count = sync_execute(
            f"""
            SELECT count(1) FROM (
                {person_query}
            )
        """,
            person_query_params,
        )[0][0]

    else:
        total_count = team.persons_seen_so_far

    blast_radius = total_count
    total_users = team.persons_seen_so_far

    return blast_radius, total_users

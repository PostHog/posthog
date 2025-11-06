from typing import Optional

import posthoganalytics
from rest_framework.exceptions import ValidationError

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import Workload
from posthog.models.cohort import Cohort
from posthog.models.filters import Filter
from posthog.models.property import GroupTypeIndex
from posthog.models.team.team import Team
from posthog.queries.base import relative_date_parse_for_feature_flag_matching


def replace_proxy_properties(team: Team, feature_flag_condition: dict):
    prop_groups = Filter(data=feature_flag_condition, team=team).property_groups

    for prop in prop_groups.flat:
        if prop.operator in ("is_date_before", "is_date_after"):
            relative_date = relative_date_parse_for_feature_flag_matching(str(prop.value))
            if relative_date:
                prop.value = relative_date.strftime("%Y-%m-%d %H:%M:%S")

    return Filter(data={"properties": prop_groups.to_dict()}, team=team)


def get_user_blast_radius(
    team: Team,
    feature_flag_condition: dict,
    group_type_index: Optional[GroupTypeIndex] = None,
):
    from posthog.queries.person_query import PersonQuery

    # No rollout % calculations here, since it makes more sense to compute that on the frontend
    properties = feature_flag_condition.get("properties") or []

    cleaned_filter = replace_proxy_properties(team, feature_flag_condition)

    if group_type_index is not None:
        try:
            from products.enterprise.backend.clickhouse.queries.groups_join_query import GroupsJoinQuery
        except Exception:
            return 0, 0

        if len(properties) > 0:
            filter = cleaned_filter

            for property in filter.property_groups.flat:
                # Special case: $group_key doesn't need a group_type_index as it refers to the key itself
                if property.key == "$group_key":
                    # Set the group_type_index to match the aggregation group type
                    property.group_type_index = group_type_index
                elif property.group_type_index is None or (property.group_type_index != group_type_index):
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
                workload=Workload.OFFLINE,  # These queries can be massive, and don't block creation of feature flags
            )[0][0]
        else:
            total_affected_count = team.groups_seen_so_far(group_type_index)

        return total_affected_count, team.groups_seen_so_far(group_type_index)

    if len(properties) > 0:
        filter = cleaned_filter
        cohort_filters = []
        for property in filter.property_groups.flat:
            if property.type in ["cohort", "precalculated-cohort", "static-cohort"]:
                cohort_filters.append(property)

        target_cohort = None

        if len(cohort_filters) == 1:
            try:
                target_cohort = Cohort.objects.get(id=cohort_filters[0].value, team__project_id=team.project_id)
            except Cohort.DoesNotExist:
                pass
            finally:
                cohort_filters = []

        if posthoganalytics.feature_enabled(
            "blast-radius-uniq-count",
            str(team.uuid),
            groups={"organization": str(team.organization.id)},
            group_properties={"organization": {"id": str(team.organization.id)}},
        ):
            person_query, person_query_params = PersonQuery(
                filter, team.id, cohort=target_cohort, cohort_filters=cohort_filters
            ).get_uniq_count()

            total_count = sync_execute(
                person_query,
                person_query_params,
            )[0][0]
        else:
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

    total_users = team.persons_seen_so_far
    blast_radius = min(total_count, total_users)

    return blast_radius, total_users

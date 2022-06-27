from datetime import timedelta
from typing import Dict, List, Optional, Tuple, Union

from dateutil.parser import isoparse
from django.utils.timezone import now

from posthog.client import query_with_columns
from posthog.models import Action, Filter, Person, Team
from posthog.models.action.util import format_action_filter
from posthog.models.event.sql import (
    SELECT_EVENT_BY_TEAM_AND_CONDITIONS_FILTERS_SQL,
    SELECT_EVENT_BY_TEAM_AND_CONDITIONS_SQL,
)
from posthog.models.property.util import parse_prop_grouped_clauses


def determine_event_conditions(
    team: Team, conditions: Dict[str, Union[str, List[str]]], long_date_from: bool
) -> Tuple[str, Dict]:
    result = ""
    params: Dict[str, Union[str, List[str]]] = {}
    for idx, (k, v) in enumerate(conditions.items()):
        if not isinstance(v, str):
            continue
        if k == "after" and not long_date_from:
            timestamp = isoparse(v).strftime("%Y-%m-%d %H:%M:%S.%f")
            result += "AND timestamp > %(after)s"
            params.update({"after": timestamp})
        elif k == "before":
            timestamp = isoparse(v).strftime("%Y-%m-%d %H:%M:%S.%f")
            result += "AND timestamp < %(before)s"
            params.update({"before": timestamp})
        elif k == "person_id":
            result += """AND distinct_id IN (%(distinct_ids)s)"""
            person = Person.objects.filter(pk=v, team_id=team.pk).first()
            distinct_ids = person.distinct_ids if person is not None else []
            params.update({"distinct_ids": list(map(str, distinct_ids))})
        elif k == "distinct_id":
            result += "AND distinct_id = %(distinct_id)s"
            params.update({"distinct_id": v})
        elif k == "event":
            result += "AND event = %(event)s"
            params.update({"event": v})
    return result, params


def query_events_list(
    filter: Filter,
    team: Team,
    request_get_query_dict: Dict,
    order_by: List[str],
    action_id: Optional[int],
    long_date_from: bool = False,
    limit: int = 100,
) -> List:
    limit += 1
    limit_sql = "LIMIT %(limit)s"
    order = "DESC" if order_by[0] == "-timestamp" else "ASC"

    conditions, condition_params = determine_event_conditions(
        team.pk,
        {
            "after": (now() - timedelta(days=1)).isoformat(),
            "before": (now() + timedelta(seconds=5)).isoformat(),
            **request_get_query_dict,
        },
        long_date_from,
    )
    prop_filters, prop_filter_params = parse_prop_grouped_clauses(
        team_id=team.pk, property_group=filter.property_groups, has_person_id_joined=False
    )

    if action_id:
        try:
            action = Action.objects.get(pk=action_id, team_id=team.pk)
        except Action.DoesNotExist:
            return []
        if action.steps.count() == 0:
            return []

        # NOTE: never accepts cohort parameters so no need for explicit person_id_joined_alias
        action_query, params = format_action_filter(team_id=team.pk, action=action)
        prop_filters += " AND {}".format(action_query)
        prop_filter_params = {**prop_filter_params, **params}

    if prop_filters != "":
        return query_with_columns(
            SELECT_EVENT_BY_TEAM_AND_CONDITIONS_FILTERS_SQL.format(
                conditions=conditions, limit=limit_sql, filters=prop_filters, order=order
            ),
            {"team_id": team.pk, "limit": limit, **condition_params, **prop_filter_params},
        )
    else:
        return query_with_columns(
            SELECT_EVENT_BY_TEAM_AND_CONDITIONS_SQL.format(conditions=conditions, limit=limit_sql, order=order),
            {"team_id": team.pk, "limit": limit, **condition_params},
        )

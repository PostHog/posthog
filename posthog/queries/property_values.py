from typing import Optional

from django.utils import timezone

from ee.clickhouse.models.property import get_property_string_expr
from ee.clickhouse.sql.events import SELECT_PROP_VALUES_SQL, SELECT_PROP_VALUES_SQL_WITH_FILTER
from ee.clickhouse.sql.person import SELECT_PERSON_PROP_VALUES_SQL, SELECT_PERSON_PROP_VALUES_SQL_WITH_FILTER
from posthog.client import sync_execute
from posthog.models.team import Team
from posthog.utils import relative_date_parse


def get_property_values_for_key(key: str, team: Team, value: Optional[str] = None):
    property_field, _ = get_property_string_expr("events", key, "%(key)s", "properties")
    parsed_date_from = "AND timestamp >= '{}'".format(relative_date_parse("-7d").strftime("%Y-%m-%d 00:00:00"))
    parsed_date_to = "AND timestamp <= '{}'".format(timezone.now().strftime("%Y-%m-%d 23:59:59"))

    if value:
        return sync_execute(
            SELECT_PROP_VALUES_SQL_WITH_FILTER.format(
                parsed_date_from=parsed_date_from, parsed_date_to=parsed_date_to, property_field=property_field
            ),
            {"team_id": team.pk, "key": key, "value": "%{}%".format(value)},
        )
    return sync_execute(
        SELECT_PROP_VALUES_SQL.format(
            parsed_date_from=parsed_date_from, parsed_date_to=parsed_date_to, property_field=property_field
        ),
        {"team_id": team.pk, "key": key},
    )


def get_person_property_values_for_key(key: str, team: Team, value: Optional[str] = None):
    property_field, _ = get_property_string_expr("person", key, "%(key)s", "properties")

    if value:
        return sync_execute(
            SELECT_PERSON_PROP_VALUES_SQL_WITH_FILTER.format(property_field=property_field),
            {"team_id": team.pk, "key": key, "value": "%{}%".format(value)},
        )
    return sync_execute(
        SELECT_PERSON_PROP_VALUES_SQL.format(property_field=property_field), {"team_id": team.pk, "key": key},
    )

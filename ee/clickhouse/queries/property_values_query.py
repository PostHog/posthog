from typing import Optional

from django.utils import timezone

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.property import get_property_string_expr
from ee.clickhouse.sql.events import SELECT_PROP_VALUES_SQL, SELECT_PROP_VALUES_SQL_WITH_FILTER
from posthog.models import Team
from posthog.utils import relative_date_parse


def get_property_values_for_key(key: str, team: Team, value: Optional[str] = None):
    parsed_date_from = "AND timestamp >= '{}'".format(relative_date_parse("-7d").strftime("%Y-%m-%d 00:00:00"))
    parsed_date_to = "AND timestamp <= '{}'".format(timezone.now().strftime("%Y-%m-%d 23:59:59"))

    property_string_expr, _ = get_property_string_expr("events", key, "%(key)s", "properties", True)

    if value:
        return sync_execute(
            SELECT_PROP_VALUES_SQL_WITH_FILTER.format(
                property_string_expr=property_string_expr,
                parsed_date_from=parsed_date_from,
                parsed_date_to=parsed_date_to,
            ),
            {"team_id": team.pk, "key": key, "value": "%{}%".format(value)},
        )

    if "FROM JSONExtractRaw" in property_string_expr:
        # only include rows which have the desired key in the properties blob
        existence_check = "AND JSONHas(properties, %(key)s)"
    else:
        # `property_string_expr` is either a table level column or a materialized column
        # so only include rows where the value is present
        existence_check = f"AND isNotNull(NULLIF({property_string_expr}, ''))"

    return sync_execute(
        SELECT_PROP_VALUES_SQL.format(
            property_string_expr=property_string_expr,
            existence_check=existence_check,
            parsed_date_from=parsed_date_from,
            parsed_date_to=parsed_date_to,
        ),
        {"team_id": team.pk, "key": key},
    )

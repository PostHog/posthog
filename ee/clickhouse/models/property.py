from typing import Dict, List, Tuple

from ee.clickhouse.client import ch_client
from ee.clickhouse.sql.events import SELECT_PROP_VALUES_SQL
from posthog.models.team import Team


def parse_filter(filters: Dict[str, str]) -> Tuple[str, Dict]:
    result = ""
    params = {}
    for idx, (k, v) in enumerate(filters.items()):
        result += "{cond}(ep.key = %(k{idx})s) AND (ep.value = %(v{idx})s)".format(
            idx=idx, cond=" AND " if idx > 0 else ""
        )
        params.update({"k{}".format(idx): k, "v{}".format(idx): v})
    return result, params


def get_property_values_for_key(key: str, team: Team):
    result = ch_client.execute(SELECT_PROP_VALUES_SQL, {"team_id": team.pk, "key": key})
    return result

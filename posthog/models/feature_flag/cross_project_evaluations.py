from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.exceptions_capture import capture_exception

QUERY = """
SELECT team_id, count() AS evaluations
FROM events
PREWHERE event = '$feature_flag_called'
WHERE JSONExtractString(properties, '$feature_flag') = %(flag_key)s
  AND team_id IN %(team_ids)s
  AND timestamp >= now() - INTERVAL 7 DAY
GROUP BY team_id
"""


def get_evaluations_7d_by_team(flag_key: str, team_ids: list[int]) -> tuple[dict[int, int], bool]:
    """Return per-team 7-day counts of `$feature_flag_called` events for flag_key.

    Returns (counts_by_team_id, available). All requested team ids are present
    in the result dict (teams with no events map to 0). `available` is False
    when ClickHouse fails; counts are then all zero.
    """
    counts = dict.fromkeys(team_ids, 0)
    if not team_ids:
        return counts, True

    tag_queries(product=Product.FEATURE_FLAGS, feature=Feature.QUERY, name="get_evaluations_7d_by_team")
    try:
        rows = sync_execute(QUERY, {"flag_key": flag_key, "team_ids": tuple(team_ids)})
    except Exception as error:
        capture_exception(error)
        return counts, False

    for team_id, evaluations in rows:
        counts[int(team_id)] = int(evaluations)
    return counts, True

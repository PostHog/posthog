from posthog.models.precalculated_person_properties.condition_watermark_sql import (
    KAFKA_PRECALC_CONDITION_WATERMARK_WS_TABLE_SQL,
    PRECALC_CONDITION_WATERMARK_WS_MV_SQL,
)


def test_ws_kafka_watermark_sql_builds():
    sql = KAFKA_PRECALC_CONDITION_WATERMARK_WS_TABLE_SQL()
    assert "kafka_precalc_condition_watermark_ws" in sql
    assert "clickhouse_precalculated_person_properties" in sql
    assert "clickhouse_precalc_condition_watermark_ws" in sql
    assert "warpstream_calculated_events" in sql


def test_ws_watermark_mv_sql_builds():
    sql = PRECALC_CONDITION_WATERMARK_WS_MV_SQL()
    assert "precalc_condition_watermark_ws_mv" in sql
    assert "TO writable_precalc_condition_watermark" in sql
    assert "FROM kafka_precalc_condition_watermark_ws" in sql
    assert "GROUP BY team_id, condition" in sql

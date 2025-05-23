from posthog import settings


# This view is accesed through an endpoint exposed to Prometheus.
# It's scraped every minute and store the results in VictoriaMetrics.
def CUSTOM_METRICS_VIEW():
    return """
    CREATE OR REPLACE VIEW custom_metrics
    AS SELECT *
    FROM custom_metrics_test
    UNION ALL
    SELECT *
    FROM custom_metrics_replication_queue
    UNION ALL
    SELECT *
    FROM custom_metrics_events_recent_lag
    """


def CUSTOM_METRICS_REPLICATION_QUEUE_VIEW():
    return f"""
    CREATE OR REPLACE VIEW custom_metrics_replication_queue
    AS
    WITH
        ['ClickHouseCustomMetric_ReplicationQueueStuckEntries', 'ClickHouseCustomMetric_ReplicationQueueMaxPostponedEntrySeconds', 'ClickHouseCustomMetric_ReplicationQueueMaxErrorEntrySeconds'] AS names,
        [toInt64(countIf(create_time < (now() - toIntervalDay(15)))), maxIf(dateDiff('seconds', create_time, last_postpone_time), last_postpone_time != '1970-01-01'), maxIf(dateDiff('seconds', create_time, last_exception_time), (last_exception_time != '1970-01-01') AND (last_exception_time > (now() - toIntervalMinute(5))))] AS values,
        ['Number of entries that have been in the replication queue for more than 15 days', 'Maximum number of seconds that an entry has been postponed', 'Maximum number of seconds that an entry has been in error'] AS descriptions,
        ['gauge', 'gauge', 'gauge'] AS types,
        arrayJoin(arrayZip(names, values, descriptions, types)) AS tpl
    SELECT
        tpl.1 AS name,
        map('table', `table`, 'instance', hostname()) AS labels,
        tpl.2 AS value,
        tpl.3 AS help,
        tpl.4 AS type
    FROM system.replication_queue
    GROUP BY `table`
    HAVING value > 0
    """


def CUSTOM_METRICS_TEST_VIEW():
    return f"""
    CREATE OR REPLACE VIEW custom_metrics_test
    AS SELECT
        'ClickHouseCustomMetric_Test' AS name,
        map('instance', hostname()) AS labels,
        1 AS value,
        'Test to check that the metric endpoint is working' AS help,
        'gauge' AS type
    """


def CUSTOM_METRICS_EVENTS_RECENT_LAG_VIEW():
    return f"""
    CREATE OR REPLACE VIEW custom_metrics_events_recent_lag
    AS
    SELECT
        'ClickHouseCustomMetric_EventsRecentIngestionLag' AS name,
        map('instance', hostname()) AS labels,
        dateDiff('second', max(timestamp), now()) AS value,
        'The number of seconds that have passed since the most recent event was inserted into events_recent table' AS help,
        'gauge' AS type
    FROM events_recent
    WHERE team_id IN (%(team_ids)s)
        AND event IN ('$heartbeat')
        AND timestamp < now() + toIntervalMinute(3) AND inserted_at > now() - toIntervalHour(3)
    GROUP BY event;
    """ % {"team_ids": settings.INGESTION_LAG_METRIC_TEAM_IDS}

import ClickHouse from '@posthog/clickhouse'

import { defaultConfig } from '../../src/config/config'
import { PluginsServerConfig } from '../../src/types'

export async function resetTestDatabaseClickhouse(extraServerConfig: Partial<PluginsServerConfig>): Promise<void> {
    const config = { ...defaultConfig, ...extraServerConfig }
    const clickhouse = new ClickHouse({
        host: config.CLICKHOUSE_HOST,
        port: 8123,
        dataObjects: true,
        queryOptions: {
            database: config.CLICKHOUSE_DATABASE,
            output_format_json_quote_64bit_integers: false,
        },
    })
    await Promise.all([
        clickhouse.querying('TRUNCATE sharded_events'),
        clickhouse.querying('TRUNCATE person'),
        clickhouse.querying('TRUNCATE person_distinct_id'),
        clickhouse.querying('TRUNCATE person_distinct_id2'),
        clickhouse.querying('TRUNCATE person_static_cohort'),
        clickhouse.querying('TRUNCATE sharded_session_recording_events'),
        clickhouse.querying('TRUNCATE plugin_log_entries'),
        clickhouse.querying('TRUNCATE events_dead_letter_queue'),
        clickhouse.querying('TRUNCATE groups'),
    ])
}

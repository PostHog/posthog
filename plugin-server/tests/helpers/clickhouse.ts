import { ClickHouseClient, createClient as createClickhouseClient } from '@clickhouse/client'
import { performance } from 'perf_hooks'

import { ClickHousePerson } from '~/types'
import { timeoutGuard } from '~/utils/db/utils'
import { isTestEnv } from '~/utils/env-utils'
import { instrumentQuery } from '~/utils/metrics'

import { logger } from '../../src/utils/logger'
import { delay } from '../../src/utils/utils'

export class Clickhouse {
    private client: ClickHouseClient

    constructor(client: ClickHouseClient) {
        this.client = client
    }

    static createClient(): ClickHouseClient {
        // NOTE: We never query CH in production so we just load these from the env directly
        const CLICKHOUSE_HOST = process.env.CLICKHOUSE_HOST ?? 'localhost'
        const CLICKHOUSE_DATABASE = process.env.CLICKHOUSE_DATABASE ?? isTestEnv() ? 'posthog_test' : 'default'
        const CLICKHOUSE_USER = process.env.CLICKHOUSE_USER ?? 'default'
        const CLICKHOUSE_PASSWORD = process.env.CLICKHOUSE_PASSWORD ?? null

        const clickhouse = createClickhouseClient({
            // We prefer to run queries on the offline cluster.
            url: `http://${CLICKHOUSE_HOST}:8123`,
            username: CLICKHOUSE_USER,
            password: CLICKHOUSE_PASSWORD || undefined,
            database: CLICKHOUSE_DATABASE,
        })

        return clickhouse
    }

    static create(): Clickhouse {
        const client = Clickhouse.createClient()
        return new Clickhouse(client)
    }

    async truncate(table: string) {
        await this.client.query({
            query: `TRUNCATE ${table}`,
            format: 'JSON',
        })
    }

    async resetTestDatabase(): Promise<void> {
        await Promise.all([
            this.truncate('sharded_events'),
            this.truncate('person'),
            this.truncate('person_distinct_id'),
            this.truncate('person_distinct_id2'),
            this.truncate('person_distinct_id_overrides'),
            this.truncate('person_static_cohort'),
            this.truncate('sharded_session_recording_events'),
            this.truncate('plugin_log_entries'),
            this.truncate('events_dead_letter_queue'),
            this.truncate('groups'),
            this.truncate('ingestion_warnings'),
            this.truncate('sharded_ingestion_warnings'),
            this.truncate('sharded_app_metrics'),
        ])
    }

    async delayUntilEventIngested<T extends any[] | number>(
        fetchData: () => T | Promise<T>,
        minLength = 1,
        delayMs = 100,
        maxDelayCount = 100
    ): Promise<T> {
        const timer = performance.now()
        let data: T | null = null
        let dataLength = 0

        for (let i = 0; i < maxDelayCount; i++) {
            data = await fetchData()
            dataLength = typeof data === 'number' ? data : data.length
            logger.debug(
                `Waiting. ${Math.round((performance.now() - timer) / 100) / 10}s since the start. ${dataLength} event${
                    dataLength !== 1 ? 's' : ''
                }.`
            )
            if (dataLength >= minLength) {
                return data
            }
            await delay(delayMs)
        }

        throw Error(`Failed to get data in time, got ${JSON.stringify(data)}`)
    }

    query(query: string): Promise<unknown[]> {
        return instrumentQuery('query.clickhouse', undefined, async () => {
            const timeout = timeoutGuard('ClickHouse slow query warning after 30 sec', { query })
            try {
                const queryResult = await this.client.query({
                    query,
                    format: 'JSON',
                })
                return (await queryResult.json()).data
            } finally {
                clearTimeout(timeout)
            }
        })
    }

    async fetchPersons(teamId?: number): Promise<ClickHousePerson[]> {
        const query = `
            SELECT id, team_id, is_identified, ts as _timestamp, properties, created_at, is_del as is_deleted, _offset
            FROM (
                SELECT id,
                    team_id,
                    max(is_identified) as is_identified,
                    max(_timestamp) as ts,
                    argMax(properties, _timestamp) as properties,
                    argMin(created_at, _timestamp) as created_at,
                    max(is_deleted) as is_del,
                    argMax(_offset, _timestamp) as _offset
                FROM person
                FINAL
                ${teamId ? `WHERE team_id = ${teamId}` : ''}
                GROUP BY team_id, id
                HAVING max(is_deleted)=0
            )
            `
        const data = await this.query(query)
        return data.map((row) => {
            const { 'person_max._timestamp': _discard1, 'person_max.id': _discard2, ...rest } = row as ClickHousePerson
            return rest
        })
    }
}

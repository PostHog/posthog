import { ClickHouseClient, ExecResult, createClient as createClickhouseClient } from '@clickhouse/client'
import { performance } from 'perf_hooks'
import { Readable } from 'stream'

import { withSpan } from '~/common/tracing/tracing-utils'
import {
    ClickHouseEvent,
    ClickHousePerson,
    ClickHousePersonDistinctId2,
    ClickhouseGroup,
    DeadLetterQueueEvent,
    InternalPerson,
    RawClickHouseEvent,
    RawSessionRecordingEvent,
} from '~/types'
import { timeoutGuard } from '~/utils/db/utils'
import { isTestEnv } from '~/utils/env-utils'
import { parseRawClickHouseEvent } from '~/utils/event'
import { parseJSON } from '~/utils/json-parse'
import { fetch } from '~/utils/request'

import { logger } from '../../src/utils/logger'
import { delay, escapeClickHouseString } from '../../src/utils/utils'

export class Clickhouse {
    private client: ClickHouseClient

    constructor(client: ClickHouseClient) {
        this.client = client
    }

    static createClient(): ClickHouseClient {
        // NOTE: We never query CH in production so we just load these from the env directly
        const CLICKHOUSE_HOST = process.env.CLICKHOUSE_HOST ?? 'localhost'
        const CLICKHOUSE_DATABASE = process.env.CLICKHOUSE_DATABASE ?? (isTestEnv() ? 'posthog_test' : 'default')
        const CLICKHOUSE_USER = process.env.CLICKHOUSE_USER ?? 'default'
        const CLICKHOUSE_PASSWORD = process.env.CLICKHOUSE_PASSWORD ?? null

        const clickhouse = createClickhouseClient({
            // We prefer to run queries on the offline cluster.
            url: `http://${CLICKHOUSE_HOST}:8123`,
            username: CLICKHOUSE_USER,
            password: CLICKHOUSE_PASSWORD || undefined,
            database: CLICKHOUSE_DATABASE,
            max_open_connections: 50, // Increased from 30 for better concurrency
            // Connection reliability improvements
            request_timeout: 30000, // 30s minutes request timeout
            keep_alive: {
                enabled: true,
                idle_socket_ttl: 30000, // 30 seconds idle timeout
            },
        })

        return clickhouse
    }

    static create(): Clickhouse {
        const client = Clickhouse.createClient()
        return new Clickhouse(client)
    }

    close(): void {
        this.client.close()
    }

    async truncate(table: string) {
        await this.exec(`TRUNCATE ${table}`)
    }

    async resetTestDatabase(): Promise<void> {
        await this.waitForHealthy()
        // NOTE: Don't do more than 5 at once otherwise we get socket timeout errors
        await Promise.allSettled([
            this.truncate('sharded_events'),
            this.truncate('person'),
            this.truncate('person_distinct_id'),
            this.truncate('person_distinct_id2'),
            this.truncate('person_distinct_id_overrides'),
        ])

        await Promise.allSettled([
            this.truncate('person_static_cohort'),
            this.truncate('sharded_session_recording_events'),
            this.truncate('events_dead_letter_queue'),
            this.truncate('groups'),
            this.truncate('ingestion_warnings'),
        ])

        await Promise.allSettled([this.truncate('sharded_ingestion_warnings'), this.truncate('sharded_app_metrics')])
    }

    async waitForHealthy(delayMs = 100, maxDelayCount = 100): Promise<void> {
        const timer = performance.now()

        for (let i = 0; i < maxDelayCount; i++) {
            try {
                await this.query('SELECT 1')
                console.log(`ClickHouse healthy after ${Math.round((performance.now() - timer) / 100) / 10}s`)
                return
            } catch (error) {
                console.log(
                    `ClickHouse not healthy yet. ${
                        Math.round((performance.now() - timer) / 100) / 10
                    }s since start. Error: ${error}`
                )
                const res = await fetch('http://localhost:8123/ping').catch((e) => {
                    console.log('ClickHouse ping failed', e)
                    return null
                })
                if (res) {
                    console.log('ClickHouse ping', res.status, await res.text())
                }

                await delay(delayMs)
            }
        }

        throw Error(`ClickHouse failed to become healthy after ${maxDelayCount * delayMs}ms`)
    }

    async delayUntilEventIngested<T extends any[] | number>(
        fetchData: () => T | Promise<T>,
        minLength = 1,
        delayMs = 100,
        maxDelayCount = 1000
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

    async exec(query: string): Promise<ExecResult<Readable>> {
        try {
            return await this.client.exec({
                query,
            })
        } catch (e) {
            console.error('Clickhouse exec failed', {
                query,
                error: e,
            })
            throw e
        }
    }

    query<T>(query: string): Promise<T[]> {
        return withSpan('clickhouse', 'query.clickhouse', { tag: 'unknown' }, async () => {
            const timeout = timeoutGuard('ClickHouse slow query warning after 30 sec', { query })
            try {
                const queryResult = await this.client.query({
                    query,
                    format: 'JSON',
                })

                const jsonData = (await queryResult.json()).data as T[]
                return jsonData
            } catch (e) {
                console.error('Clickhouse query failed', {
                    query,
                    error: e,
                })
                throw e
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
            const { 'person_max._timestamp': _discard1, 'person_max.id': _discard2, ...rest }: any = row
            return rest
        })
    }

    async fetchDistinctIds(person: InternalPerson): Promise<ClickHousePersonDistinctId2[]> {
        const query = `
            SELECT *
            FROM person_distinct_id2
            FINAL
            WHERE person_id='${escapeClickHouseString(person.uuid)}'
              AND team_id='${person.team_id}'
              AND is_deleted=0
            ORDER BY _offset`
        return await this.query<ClickHousePersonDistinctId2>(query)
    }

    public async fetchDistinctIdValues(person: InternalPerson): Promise<string[]> {
        const personDistinctIds = await this.fetchDistinctIds(person)
        return personDistinctIds.map((pdi) => pdi.distinct_id)
    }

    public async fetchEvents(): Promise<ClickHouseEvent[]> {
        const queryResult = await this.query<RawClickHouseEvent>(`SELECT * FROM events ORDER BY timestamp ASC`)
        return queryResult.map(parseRawClickHouseEvent)
    }

    public async fetchDeadLetterQueueEvents(): Promise<DeadLetterQueueEvent[]> {
        const result = await this.query<DeadLetterQueueEvent>(
            `SELECT * FROM events_dead_letter_queue ORDER BY _timestamp ASC`
        )
        return result
    }

    // SessionRecordingEvent

    public async fetchSessionRecordingEvents(): Promise<RawSessionRecordingEvent[]> {
        const events = await this.query<RawSessionRecordingEvent>(`SELECT * FROM session_recording_events`)
        return events.map((event) => {
            return {
                ...event,
                snapshot_data: event.snapshot_data ? parseJSON(event.snapshot_data) : null,
            }
        })
    }

    public async fetchClickhouseGroups(): Promise<ClickhouseGroup[]> {
        const query = `
        SELECT group_type_index, group_key, created_at, team_id, group_properties FROM groups FINAL
        `
        return await this.query<ClickhouseGroup>(query)
    }
}

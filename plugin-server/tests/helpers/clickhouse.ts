import { ClickHouseClient, createClient } from '@clickhouse/client'

import { defaultConfig } from '../../src/config/config'
import {
    KAFKA_APP_METRICS,
    KAFKA_EVENTS_JSON,
    KAFKA_GROUPS,
    KAFKA_INGESTION_WARNINGS,
    KAFKA_PERSON,
    KAFKA_PERSON_DISTINCT_ID,
    KAFKA_PLUGIN_LOG_ENTRIES,
} from '../../src/config/kafka-topics'
import {
    ClickHouseEvent,
    ClickhouseGroup,
    ClickHousePerson,
    ClickHousePersonDistinctId2,
    DeadLetterQueueEvent,
} from '../../src/types'
import { KafkaProducerWrapper } from '../../src/utils/db/kafka-producer-wrapper'
import { parseRawClickHouseEvent } from '../../src/utils/event'
import { status } from '../../src/utils/status'
import { delay } from '../../src/utils/utils'
import { AppMetrics } from '../../src/worker/ingestion/app-metrics'

let clickHouseClient: ClickHouseClient

beforeAll(() => {
    // To avoid needing to handle eventual consistency in tests, and including
    // the extra dependency of Kafka in tests, we mock the KafkaProducerWrapper
    // class to instead INSERT directly into ClickHouse. This ensures that we
    // have read after write consistency and thus do not need to wait arbitrary
    // amounts of time for data to be available in ClickHouse.
    //
    // We could simply store the data in memory, but the tests rely on e.g.
    // MATERIALIZED columns which would be difficult to replicate in memory.
    clickHouseClient = createClient({
        host: `http://${defaultConfig.CLICKHOUSE_HOST}:8123`,
        username: defaultConfig.CLICKHOUSE_USER,
        password: defaultConfig.CLICKHOUSE_PASSWORD || undefined,
        database: defaultConfig.CLICKHOUSE_DATABASE,
        clickhouse_settings: {
            // To ensure compability with existing test expectations, do not
            // quote 64-bit integers.
            output_format_json_quote_64bit_integers: 0,
        },
    })
})

beforeEach(() => {
    jest.spyOn(KafkaProducerWrapper.prototype, 'queueMessage').mockImplementation(async (record) => {
        // Insert the data into ClickHouse, first mapping the topic name to a
        // table to insert into. Note that although this mock is for
        // queueMessage singular, we actually have multiple events in
        // `record.messages`.
        const table = {
            [KAFKA_EVENTS_JSON]: 'sharded_events',
            [KAFKA_PERSON]: 'person',
            [KAFKA_PERSON_DISTINCT_ID]: 'person_distinct_id2',
            [KAFKA_GROUPS]: 'groups',
            [KAFKA_INGESTION_WARNINGS]: 'ingestion_warnings',
            [KAFKA_PLUGIN_LOG_ENTRIES]: 'plugin_log_entries',
            [KAFKA_APP_METRICS]: 'app_metrics',
        }[record.topic]

        if (!table) {
            throw Error(`Unknown topic ${record.topic}`)
        }

        // Now generate JSON strings to be used with ClickHouse's JSONEachRow
        // and perform the insert.
        const rows = record.messages.flatMap((message) => (message.value ? [JSON.parse(message.value.toString())] : []))
        await clickHouseClient.insert({ table, format: 'JSONEachRow', values: rows })
    })
})

afterEach(async () => {
    await clickHouseClient.close()
})

export async function delayUntilEventIngested<T extends any[] | number>(
    fetchData: () => T | Promise<T>,
    minLength = 1,
    delayMs = 100,
    maxDelayCount = 1
): Promise<T> {
    const timer = performance.now()
    let data: T | undefined = undefined
    let dataLength = 0
    for (let i = 0; i < maxDelayCount; i++) {
        data = await fetchData()
        dataLength = typeof data === 'number' ? data : data.length
        status.debug(
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

export const fetchEvents = async (teamId: number) => {
    // Pull out the events from the clickHouseRows object defaulting to using
    // the global teamId if not specified
    return await clickHouseClient
        .query({
            query: `
                SELECT * FROM events 
                WHERE team_id = ${teamId} 
                ORDER BY timestamp ASC
            `,
        })
        .then((res) => res.json<{ data: ClickHouseEvent[] }>())
        .then((res) => res.data.map(parseRawClickHouseEvent))
}

export const fetchClickHousePersons = async (teamId: number, includeDeleted = false) => {
    // Pull out the persons from the ClickHouse using clickHouseClient. Note the
    // ClickHouse persons table is a ReplacingMergeTree table using the person
    // id for the key, which means we just want to get the latest version of
    // each person. Version is specified by the `version` attribute of the rows
    // and is a monotonically increasing number per person id.
    //
    // Further, if the is_deleted attribute is true for the latest version, we
    // do not want to include that person in the results.
    const query = `
        SELECT * FROM person FINAL
        WHERE team_id = ${teamId}
        ${includeDeleted ? '' : 'AND NOT is_deleted'}
        ORDER BY id, version DESC
    `
    return await clickHouseClient
        .query({ query })
        .then((res) => res.json<{ data: ClickHousePerson[] }>())
        .then((res) => res.data)
}

export const fetchClickhouseGroups = async (teamId: number) => {
    // Pull out the groups from ClickHouse using clickHouseClient. Note the
    // ClickHouse groups table is a ReplacingMergeTree table using the group
    // id for the key, which means we just want to get the latest version of
    // each group. Version is specified by the `version` attribute of the rows
    // and is a monotonically increasing number per group id.

    const query = `
        SELECT group_type_index, group_key, created_at, team_id, group_properties 
        FROM groups FINAL
        WHERE team_id = ${teamId}
    `

    return await clickHouseClient
        .query({ query })
        .then((res) => res.json<{ data: ClickhouseGroup[] }>())
        .then((res) => res.data)
}

export async function fetchClickHousePersonsWithVersionHigerEqualThan(teamId: number, version = 1) {
    // Fetch only persons with version higher or equal than the specified
    // version.
    const query = `SELECT * FROM person FINAL WHERE team_id = ${teamId} AND version >= ${version}`

    return await clickHouseClient
        .query({ query })
        .then((res) => res.json<{ data: ClickHousePerson[] }>())
        .then((res) => res.data)
}

export async function fetchClickHouseDistinctIdValues(teamId: number, personId: string) {
    // Pull just the distinct_ids for the specified personId
    const query = `
        SELECT distinct_id FROM person_distinct_id2 FINAL 
        WHERE team_id = ${teamId} AND person_id = '${personId}'
        ORDER BY person_id, version DESC
    `

    return await clickHouseClient
        .query({ query })
        .then((res) => res.json<{ data: ClickHousePersonDistinctId2[] }>())
        .then((res) => res.data.map((row) => row.distinct_id))
}

export async function fetchDistinctIdsClickhouse(teamId: number, personId?: string, onlyVersionHigherEqualThan = 0) {
    // Pull out the person distinct id rows from the clickHouseRows object.

    // Note the ClickHouse persons_distinct_id table is
    // a ReplacingMergeTree table using the person id for the key, which means
    // we just want to get the latest version of each person. Version is
    // specified by the `version` attribute of the rows and is a monotonically
    // increasing number per person id.
    //
    // Further, if the is_deleted attribute is true for the latest version, we
    // do not want to include that person in the results.
    const query = `
        SELECT * FROM person_distinct_id2 FINAL
        WHERE team_id = ${teamId} AND is_deleted = 0
        ${personId ? `AND person_id = '${personId}'` : ''}
        ${onlyVersionHigherEqualThan > 0 ? `AND version >= ${onlyVersionHigherEqualThan}` : ''}
        ORDER BY person_id, version DESC
    `
    return await clickHouseClient
        .query({ query })
        .then((res) => res.json<{ data: ClickHousePersonDistinctId2[] }>())
        .then((res) => res.data)
}

export async function fetchDistinctIdsClickhouseVersion1(teamId: number) {
    // Fetch only distinct ids with version 1.
    return await fetchDistinctIdsClickhouse(teamId, undefined, 1)
}

export async function fetchDeadLetterQueueEvents(teamId: number) {
    const query = `
        SELECT * FROM events_dead_letter_queue 
        WHERE team_id = ${teamId}
        ORDER BY _timestamp ASC
    `
    return await clickHouseClient
        .query({ query })
        .then((res) => res.json<{ data: DeadLetterQueueEvent[] }>())
        .then((res) => res.data)
}

export async function fetchAppMetrics(teamId: number) {
    const query = `
        SELECT * FROM app_metrics FINAL
        WHERE team_id = ${teamId}
        ORDER BY timestamp ASC
    `

    return await clickHouseClient
        .query({ query })
        .then((res) => res.json<{ data: AppMetrics[] }>().then((res) => res.data))
}

export async function fetchIngestionWarnings(teamId: number) {
    const query = `
        SELECT * FROM ingestion_warnings 
        WHERE team_id = ${teamId}
        ORDER BY timestamp ASC
    `

    return await clickHouseClient.query({ query }).then((res) => res.json<{ data: any[] }>().then((res) => res.data))
}

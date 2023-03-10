import { KAFKA_EVENTS_JSON, KAFKA_GROUPS, KAFKA_PERSON, KAFKA_PERSON_DISTINCT_ID } from '../../src/config/kafka-topics'
import { ClickHouseEvent, ClickHousePerson, ClickHousePersonDistinctId2 } from '../../src/types'
import { KafkaProducerWrapper } from '../../src/utils/db/kafka-producer-wrapper'
import { parseRawClickHouseEvent } from '../../src/utils/event'
import { status } from '../../src/utils/status'
import { delay } from '../../src/utils/utils'

const clickHouseRows: Record<number, Record<string, any[]>> = {}

beforeAll(() => {
    // Typically we would ingest into ClickHouse. Instead we can just mock and
    // record the produced messages. For all messages we append to the
    // approriate place in the clickHouseRows object. Note that while this is
    // called `queueMessage` singular, it actually contains multiple messages as
    // `record.messages` is an array. Use the team_id in the message's value to
    // determine which team it belongs to.
    jest.spyOn(KafkaProducerWrapper.prototype, 'queueMessage').mockImplementation(async (record) => {
        for (const message of record.messages) {
            const row = message.value ? JSON.parse(message.value.toString()) : null
            const teamId = row.team_id
            const topic = record.topic

            // To maintain the same test assertions as before adding these
            // ClickHouse mocks, we need to convert ClickHouse formatted date
            // strings of the form 2022-01-01 00:00:00 i.e. without millisecond
            // granularity to ones with milliseconds i.e. by simply appending
            // '.000'. We also need to convert boolean values to 1 or 0. To do
            // so we convert the values or the row object.
            if (row) {
                for (const key of Object.keys(row)) {
                    const value = row[key]
                    if (typeof value === 'string' && value.match(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/)) {
                        row[key] = `${value}.000`
                    } else if (typeof value === 'boolean') {
                        row[key] = value ? 1 : 0
                    }
                }
            }

            if (!clickHouseRows[teamId]) {
                clickHouseRows[teamId] = {}
            }
            if (!clickHouseRows[teamId][topic]) {
                clickHouseRows[teamId][topic] = []
            }
            clickHouseRows[teamId][topic].push(row)
        }
        return Promise.resolve()
    })
})

export async function delayUntilEventIngested<T extends any[] | number>(
    fetchData: () => T | Promise<T>,
    minLength = 1,
    delayMs = 100,
    maxDelayCount = 100
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

export const fetchEvents = (teamId: number): ClickHouseEvent[] => {
    // Pull out the events from the clickHouseRows object defaulting to using
    // the global teamId if not specified
    const events = clickHouseRows[teamId][KAFKA_EVENTS_JSON] ?? []
    return events.map(parseRawClickHouseEvent)
}

export const fetchClickHousePersons = (teamId: number, includeDeleted = false): ClickHousePerson[] => {
    // Pull out the persons from the clickHouseRows object defaulting to using
    // the global teamId if not specified. Note the ClickHouse persons table is
    // a ReplacingMergeTree table using the person id for the key, which means
    // we just want to get the latest version of each person. Version is
    // specified by the `version` attribute of the rows and is a monotonically
    // increasing number per person id.
    //
    // Further, if the is_deleted attribute is true for the latest version, we
    // do not want to include that person in the results.
    const persons = clickHouseRows[teamId][KAFKA_PERSON] ?? []
    const latestPersons: Record<string, ClickHousePerson> = {}
    for (const person of persons) {
        const personId = person.id
        if (!latestPersons[personId] || latestPersons[personId].version < person.version) {
            latestPersons[personId] = person
        }
    }
    return Object.values(latestPersons)
        .filter((p) => includeDeleted || !p.is_deleted)
        .sort((a, b) => b.id.localeCompare(a.id))
}

export const fetchClickhouseGroups = (teamId: number): any[] => {
    // Pull out the groups from the clickHouseRows object
    const groups = clickHouseRows[teamId][KAFKA_GROUPS] ?? []
    return groups.map((group) => ({
        ...group,
        properties: group.properties ? JSON.parse(group.properties) : undefined,
        team_id: teamId,
        version: undefined,
    }))
}

export function fetchClickHousePersonsWithVersionHigerEqualThan(teamId: number, version = 1) {
    // Fetch only persons with version higher or equal than the specified version.
    return fetchClickHousePersons(teamId).filter((person) => person.version >= version)
}

export function fetchDistinctIdsClickhouse(teamId: number, personId?: string, onlyVersionHigherEqualThan = 0) {
    // Pull out the person distinct id rows from the clickHouseRows object.

    // Note the ClickHouse persons_distinct_id table is
    // a ReplacingMergeTree table using the person id for the key, which means
    // we just want to get the latest version of each person. Version is
    // specified by the `version` attribute of the rows and is a monotonically
    // increasing number per person id.
    //
    // Further, if the is_deleted attribute is true for the latest version, we
    // do not want to include that person in the results.
    const personDistinctIdRows = clickHouseRows[teamId][KAFKA_PERSON_DISTINCT_ID] ?? []
    const latestDistinctIds: Record<string, ClickHousePersonDistinctId2> = {}
    for (const row of personDistinctIdRows) {
        const distinctId = row.distinct_id
        if (!latestDistinctIds[distinctId] || latestDistinctIds[distinctId].version < row.version) {
            latestDistinctIds[distinctId] = row
        }
    }

    return Object.values(latestDistinctIds)
        .filter((p) => !personId || p.person_id === personId)
        .filter((p) => p.version >= onlyVersionHigherEqualThan)
        .map((p) => p.distinct_id)
}

export function fetchDistinctIdsClickhouseVersion1(teamId: number) {
    // Fetch only distinct ids with version 1.
    return fetchDistinctIdsClickhouse(teamId, undefined, 1)
}

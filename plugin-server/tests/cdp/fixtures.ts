import { randomUUID } from 'crypto'
import { Message } from 'node-rdkafka'

import { HogFunctionType } from '../../src/cdp/types'
import { ClickHouseTimestamp, RawClickHouseEvent, Team } from '../../src/types'
import { PostgresRouter } from '../../src/utils/db/postgres'
import { insertRow } from '../helpers/sql'

export const insertHogFunction = async (
    postgres: PostgresRouter,
    team: Team,
    hogFunction: Partial<HogFunctionType> = {}
) => {
    const item: HogFunctionType = {
        id: randomUUID(),
        team_id: team.id,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        created_by_id: 1001,
        enabled: true,
        deleted: false,
        description: '',
        hog: '',
        ...hogFunction,
    }

    const res = await insertRow(postgres, 'posthog_hogfunction', item)

    return res
}

export const createIncomingEvent = (teamId: number, data: Partial<RawClickHouseEvent>): RawClickHouseEvent => {
    return {
        team_id: teamId,
        created_at: new Date().toISOString() as ClickHouseTimestamp,
        elements_chain: '[]',
        person_created_at: new Date().toISOString() as ClickHouseTimestamp,
        person_properties: '{}',
        distinct_id: 'distinct_id_1',
        uuid: randomUUID(),
        event: '$pageview',
        timestamp: new Date().toISOString() as ClickHouseTimestamp,
        properties: '{}',
        ...data,
    }
}

export const createMessage = (event: RawClickHouseEvent, overrides: Partial<Message> = {}): Message => {
    return {
        partition: 1,
        topic: 'test',
        offset: 0,
        timestamp: overrides.timestamp ?? Date.now(),
        size: 1,
        ...overrides,
        value: Buffer.from(JSON.stringify(event)),
    }
}

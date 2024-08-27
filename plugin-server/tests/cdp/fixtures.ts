import { randomUUID } from 'crypto'
import { Message } from 'node-rdkafka'

import { HogFunctionInvocationGlobals, HogFunctionType, IntegrationType } from '../../src/cdp/types'
import { ClickHouseTimestamp, RawClickHouseEvent, Team } from '../../src/types'
import { PostgresRouter } from '../../src/utils/db/postgres'
import { insertRow } from '../helpers/sql'

export const createHogFunction = (hogFunction: Partial<HogFunctionType>) => {
    const item: HogFunctionType = {
        id: randomUUID(),
        team_id: 1,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        created_by_id: 1001,
        enabled: true,
        deleted: false,
        description: '',
        hog: '',
        ...hogFunction,
    }

    return item
}

export const createIntegration = (integration: Partial<IntegrationType>) => {
    const item: IntegrationType = {
        team_id: 1,
        errors: '',
        created_at: new Date().toISOString(),
        created_by_id: 1001,
        ...integration,
    }

    return item
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

export const insertHogFunction = async (
    postgres: PostgresRouter,
    team_id: Team['id'],
    hogFunction: Partial<HogFunctionType> = {}
): Promise<HogFunctionType> => {
    const res = await insertRow(
        postgres,
        'posthog_hogfunction',
        createHogFunction({
            ...hogFunction,
            team_id: team_id,
        })
    )
    return res
}

export const insertIntegration = async (
    postgres: PostgresRouter,
    team_id: Team['id'],
    integration: Partial<IntegrationType> = {}
): Promise<IntegrationType> => {
    const res = await insertRow(
        postgres,
        'posthog_integration',
        createIntegration({
            ...integration,
            team_id: team_id,
        })
    )
    return res
}

export const createHogExecutionGlobals = (
    data: Partial<HogFunctionInvocationGlobals> = {}
): HogFunctionInvocationGlobals => {
    return {
        ...data,
        person: {
            uuid: 'uuid',
            name: 'test',
            url: 'http://localhost:8000/persons/1',
            properties: {
                $lib_version: '1.2.3',
            },
            ...(data.person ?? {}),
        },
        project: {
            id: 1,
            name: 'test',
            url: 'http://localhost:8000/projects/1',
            ...(data.project ?? {}),
        },
        event: {
            uuid: 'uuid',
            name: 'test',
            distinct_id: 'distinct_id',
            url: 'http://localhost:8000/events/1',
            properties: {
                $lib_version: '1.2.3',
            },
            timestamp: new Date().toISOString(),
            ...(data.event ?? {}),
        },
    }
}

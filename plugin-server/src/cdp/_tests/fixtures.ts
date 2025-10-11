import { randomUUID } from 'crypto'
import { DateTime } from 'luxon'
import { Message } from 'node-rdkafka'

import { insertRow } from '~/tests/helpers/sql'

import { ClickHousePerson, ClickHouseTimestamp, ProjectId, RawClickHouseEvent, Team } from '../../types'
import { PostgresRouter } from '../../utils/db/postgres'
import { UUIDT } from '../../utils/utils'
import { CohortMembershipChange } from '../consumers/cdp-cohort-membership.consumer'
import { CdpInternalEvent } from '../schema'
import { compileHog } from '../templates/compiler'
import {
    CyclotronJobInvocationHogFunction,
    CyclotronJobQueueKind,
    DBHogFunctionTemplate,
    HogFunctionInvocationGlobals,
    HogFunctionInvocationGlobalsWithInputs,
    HogFunctionTemplateCompiled,
    HogFunctionType,
    IntegrationType,
} from '../types'

export const SAMPLE_GLOBALS = {
    event: {
        uuid: 'uuid',
        event: 'test',
        distinct_id: 'distinct_id',
        properties: {
            email: 'test@posthog.com',
        },
        elements_chain: '',
        timestamp: '',
        url: '',
    },
    project: {
        id: 1,
        name: 'test',
        url: 'http://localhost:8000/projects/1',
    },
}

export const createHogFunction = (hogFunction: Partial<HogFunctionType>) => {
    const item: HogFunctionType = {
        id: randomUUID(),
        type: 'destination',
        name: 'Hog Function',
        team_id: 1,
        enabled: true,
        hog: '',
        bytecode: [],
        ...hogFunction,
    } as HogFunctionType

    return item
}

export const createIntegration = (integration: Partial<IntegrationType>) => {
    const item: IntegrationType = {
        team_id: 1,
        id: integration.id ?? 1,
        kind: integration.kind ?? 'slack',
        config: {},
        sensitive_config: {},
        ...integration,
    }

    return item
}

export const createIncomingEvent = (teamId: number, data: Partial<RawClickHouseEvent>): RawClickHouseEvent => {
    return {
        team_id: teamId,
        project_id: teamId as ProjectId,
        created_at: new Date().toISOString() as ClickHouseTimestamp,
        elements_chain: '[]',
        person_created_at: new Date().toISOString() as ClickHouseTimestamp,
        person_properties: '{}',
        distinct_id: 'distinct_id_1',
        uuid: randomUUID(),
        event: '$pageview',
        timestamp: new Date().toISOString() as ClickHouseTimestamp,
        properties: '{}',
        person_mode: 'full',
        ...data,
    }
}

export const createKafkaMessage = (event: any, overrides: Partial<Message> = {}): Message => {
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

export const createInternalEvent = (teamId: number, data: Partial<CdpInternalEvent>): CdpInternalEvent => {
    return {
        team_id: teamId,
        event: {
            timestamp: DateTime.now().toISO(),
            properties: {},
            uuid: randomUUID(),
            event: '$pageview',
            distinct_id: 'distinct_id',
        },
        ...data,
    }
}

export const createClickhousePerson = (teamId: number, data: Partial<ClickHousePerson>): ClickHousePerson => {
    return {
        team_id: teamId,
        id: randomUUID(),
        created_at: new Date().toISOString(),
        properties: JSON.stringify({
            email: 'test@posthog.com',
        }),
        is_identified: 1,
        is_deleted: 0,
        timestamp: new Date().toISOString(),
        version: 1,
        ...data,
    }
}

export const insertHogFunction = async (
    postgres: PostgresRouter,
    team_id: Team['id'],
    hogFunction: Partial<HogFunctionType> = {}
): Promise<HogFunctionType> => {
    // This is only used for testing so we need to override some values

    const res = await insertRow(postgres, 'posthog_hogfunction', {
        ...createHogFunction({
            ...hogFunction,
            team_id: team_id,
        }),
        description: '',
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        created_by_id: 1001,
        deleted: false,
    })
    return res
}

export const createHogFunctionTemplate = (
    hogFunctionTemplate: Partial<HogFunctionTemplateCompiled>
): HogFunctionTemplateCompiled => {
    return {
        id: randomUUID(),
        status: 'stable',
        free: true,
        type: 'destination',
        name: 'Hog Function Template',
        description: 'Hog Function Template',
        code_language: 'hog',
        code: 'Hog Function Template',
        inputs_schema: [],
        category: [],
        bytecode: [],
        ...hogFunctionTemplate,
    }
}

export const insertHogFunctionTemplate = async (
    postgres: PostgresRouter,
    hogFunctionTemplate: Partial<HogFunctionTemplateCompiled> = {}
): Promise<DBHogFunctionTemplate> => {
    // This is only used for testing so we need to override some values

    const template = createHogFunctionTemplate({
        ...hogFunctionTemplate,
    })
    if (template.code_language === 'hog') {
        template.bytecode = await compileHog(template.code)
    }

    const res = await insertRow(postgres, 'posthog_hogfunctiontemplate', {
        id: randomUUID(),
        template_id: template.id,
        sha: 'sha',
        name: template.name,
        description: template.description,
        code: template.code,
        code_language: template.code_language,
        status: template.status,
        free: template.free,
        category: template.category,
        icon_url: template.icon_url,
        filters: template.filters,
        masking: template.masking,
        mappings: template.mappings,
        bytecode: template.bytecode,
        inputs_schema: template.inputs_schema,
        type: template.type,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
    })
    return res
}

export const insertIntegration = async (
    postgres: PostgresRouter,
    team_id: Team['id'],
    integration: Partial<IntegrationType> = {}
): Promise<IntegrationType> => {
    const res = await insertRow(postgres, 'posthog_integration', {
        ...createIntegration({
            ...integration,
            team_id: team_id,
        }),
        errors: '',
        created_at: new Date().toISOString(),
        created_by_id: 1001,
    })
    return res
}

export const createHogExecutionGlobals = (
    data: Partial<HogFunctionInvocationGlobals> = {}
): HogFunctionInvocationGlobals => {
    return {
        groups: {},
        ...data,
        person: {
            id: 'uuid',
            name: 'test',
            url: 'http://localhost:8000/persons/1',
            properties: {
                email: 'test@posthog.com',
                first_name: 'Pumpkin',
            },
            ...data.person,
        },
        project: {
            id: 1,
            name: 'test',
            url: 'http://localhost:8000/projects/1',
            ...data.project,
        },
        event: {
            uuid: 'uuid',
            event: 'test',
            elements_chain: '',
            distinct_id: 'distinct_id',
            url: 'http://localhost:8000/events/1',
            properties: {
                $lib_version: '1.2.3',
            },
            timestamp: new Date().toISOString(),
            ...data.event,
        },
    }
}

export const createExampleInvocation = (
    _hogFunction: Partial<HogFunctionType> = {},
    _globals: Partial<HogFunctionInvocationGlobalsWithInputs> = {},
    queue: CyclotronJobQueueKind = 'hog'
): CyclotronJobInvocationHogFunction => {
    const hogFunction = createHogFunction(_hogFunction)
    // Add the source of the trigger to the globals

    const globals = createHogExecutionGlobals(_globals)
    globals.source = {
        name: hogFunction.name ?? `Hog function: ${hogFunction.id}`,
        url: `${globals.project.url}/pipeline/destinations/hog-${hogFunction.id}/configuration/`,
    }

    return {
        id: new UUIDT().toString(),
        state: {
            globals: globals as HogFunctionInvocationGlobalsWithInputs,
            timings: [],
            attempts: 0,
        },
        teamId: hogFunction.team_id,
        functionId: hogFunction.id,
        hogFunction,
        queue,
        queuePriority: 0,
    }
}

// Cohort Membership Test Helpers
export const createCohortMembershipEvent = (
    overrides: Partial<CohortMembershipChange> = {}
): CohortMembershipChange => {
    return {
        personId: new UUIDT().toString(),
        cohortId: 1,
        teamId: 1,
        cohort_membership_changed: 'entered',
        ...overrides,
    }
}

export const createCohortMembershipEvents = (events: Partial<CohortMembershipChange>[]): CohortMembershipChange[] => {
    return events.map((event) => createCohortMembershipEvent(event))
}

export interface CohortMembershipRecord {
    team_id: number
    cohort_id: number
    person_id: string
    in_cohort: boolean
    last_updated?: Date
}

export const insertCohortMembership = async (
    db: PostgresRouter,
    membership: Partial<CohortMembershipRecord>
): Promise<CohortMembershipRecord> => {
    const record: CohortMembershipRecord = {
        team_id: 1,
        cohort_id: 1,
        person_id: new UUIDT().toString(),
        in_cohort: true,
        ...membership,
    }

    // insertRow now automatically determines the correct database based on table name
    return await insertRow(db, 'cohort_membership', record)
}

export const insertCohortMemberships = async (
    db: PostgresRouter,
    memberships: Partial<CohortMembershipRecord>[]
): Promise<CohortMembershipRecord[]> => {
    const results = []
    for (const membership of memberships) {
        results.push(await insertCohortMembership(db, membership))
    }
    return results
}

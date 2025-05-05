import { randomUUID } from 'crypto'
import { Message } from 'node-rdkafka'

import { insertRow } from '~/tests/helpers/sql'

import { ClickHouseTimestamp, ProjectId, RawClickHouseEvent, Team } from '../../types'
import { PostgresRouter } from '../../utils/db/postgres'
import { UUIDT } from '../../utils/utils'
import { CdpInternalEvent } from '../schema'
import { compileHog } from '../templates/compiler'
import {
    HogFunctionInvocation,
    HogFunctionInvocationGlobals,
    HogFunctionInvocationGlobalsWithInputs,
    HogFunctionTemplateType,
    HogFunctionType,
    IntegrationType,
} from '../types'

export const createHogFunction = (hogFunction: Partial<HogFunctionType>) => {
    const item: HogFunctionType = {
        id: randomUUID(),
        type: 'destination',
        name: 'Hog Function',
        team_id: 1,
        enabled: true,
        ...hogFunction,
    } as HogFunctionType

    return item
}

export const createIntegration = (integration: Partial<IntegrationType>) => {
    const item: IntegrationType = {
        team_id: 1,
        errors: '',
        created_at: new Date().toISOString(),
        created_by_id: 1001,
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
            timestamp: new Date().toISOString(),
            properties: {},
            uuid: randomUUID(),
            event: '$pageview',
            distinct_id: 'distinct_id',
        },
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
        // Ensure these fields are null unless explicitly set
        hog: hogFunction.hog ?? null,
        bytecode: hogFunction.bytecode ?? null,
        inputs_schema: hogFunction.inputs_schema ?? null,
        mappings: hogFunction.mappings ?? null,
        description: '',
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        created_by_id: 1001,
        deleted: false,
    })
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
            event: 'test',
            elements_chain: '',
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

export const createInvocation = (
    _hogFunction: Partial<HogFunctionType> = {},
    _globals: Partial<HogFunctionInvocationGlobals> = {}
): HogFunctionInvocation => {
    const hogFunction = createHogFunction(_hogFunction)
    // Add the source of the trigger to the globals

    const globals = createHogExecutionGlobals(_globals)
    globals.source = {
        name: hogFunction.name ?? `Hog function: ${hogFunction.id}`,
        url: `${globals.project.url}/pipeline/destinations/hog-${hogFunction.id}/configuration/`,
    }

    return {
        id: new UUIDT().toString(),
        // NOTE: This is due to some legacy code that checks for inputs and uses it. BW will fix later.
        globals: globals as HogFunctionInvocationGlobalsWithInputs,
        teamId: hogFunction.team_id,
        hogFunction,
        queue: 'hog',
        timings: [],
        queuePriority: 0,
    }
}

export const createHogFunctionTemplate = async (template: Partial<HogFunctionTemplateType>) => ({
    id: randomUUID(),
    template_id: 'default_template_id',
    code: 'return event',
    bytecode: await compileHog('return event'),
    inputs_schema: [
        {
            type: 'string',
            key: 'test_input',
            label: 'Test Input',
            required: true,
            default: 'test',
        },
        {
            type: 'boolean',
            key: 'enabled',
            label: 'Enabled',
            default: true,
        },
    ],
    mappings: [
        {
            inputs_schema: [
                {
                    type: 'string',
                    key: 'field_mapping',
                    label: 'Field Mapping',
                    required: true,
                    default: 'event.properties',
                },
            ],
            inputs: {
                field_mapping: {
                    value: 'event.properties',
                },
            },
            filters: null,
        },
    ],
    sha: 'sha1',
    name: 'Test Template',
    code_language: 'hog',
    type: 'destination',
    status: 'alpha',
    category: '[]',
    free: false,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    ...template,
})

export const insertHogFunctionTemplate = async (
    postgres: PostgresRouter,
    template: Partial<HogFunctionTemplateType> = {}
): Promise<HogFunctionTemplateType> => {
    const res = await insertRow(postgres, 'posthog_hogfunctiontemplate', {
        ...(await createHogFunctionTemplate({
            ...template,
        })),
    })
    return res
}

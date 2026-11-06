import { z } from 'zod'

// The materialization schedules PostHog accepts, as posthog-cli writes them, with their refresh interval.
export const SCHEDULES = {
    '15min': 900,
    '30min': 1800,
    '1hour': 3600,
    '6hour': 21600,
    '12hour': 43200,
    '24hour': 86400,
    '7day': 604800,
} as const

export type Schedule = keyof typeof SCHEDULES

export const SCHEDULE_LABELS: Record<Schedule, string> = {
    '15min': 'every 15 min',
    '30min': 'every 30 min',
    '1hour': 'hourly',
    '6hour': 'every 6 hours',
    '12hour': 'every 12 hours',
    '24hour': 'daily',
    '7day': 'weekly',
}

export function scheduleFor(seconds: number | null | undefined): Schedule | undefined {
    return (Object.keys(SCHEDULES) as Schedule[]).find((schedule) => SCHEDULES[schedule] === seconds)
}

// The same fields and names as the files posthog-cli writes, so either CLI reads the other's files.
export const EndpointFile = z
    .strictObject({
        name: z.string().min(1, 'name is required'),
        description: z.string().optional(),
        query: z.string().optional(),
        query_definition: z.record(z.string(), z.unknown()).optional(),
        variables: z
            .array(
                z.strictObject({
                    name: z.string().min(1),
                    type: z.string().min(1),
                    default: z.unknown().optional(),
                })
            )
            .optional(),
        materialization: z
            .strictObject({
                enabled: z.boolean().default(false),
                schedule: z
                    .enum(Object.keys(SCHEDULES) as [Schedule, ...Schedule[]], {
                        error: `schedule must be one of ${Object.keys(SCHEDULES).join(', ')}`,
                    })
                    .optional(),
            })
            .optional(),
    })
    .refine((file) => file.query !== undefined || file.query_definition !== undefined, {
        message: 'the file needs a query or a query_definition',
    })

export type EndpointFile = z.infer<typeof EndpointFile>
export type EndpointVariable = NonNullable<EndpointFile['variables']>[number]

// The API answers keep fields hog doesn't name, because `hog endpoints get` prints the whole answer.
const MaterializationStatus = z.looseObject({
    status: z.string().nullish(),
    can_materialize: z.boolean().optional(),
    last_materialized_at: z.string().nullish(),
    error: z.string().nullish(),
    reason: z.string().nullish(),
})

export const Endpoint = z.looseObject({
    id: z.string(),
    name: z.string(),
    description: z.string().nullish(),
    query: z.record(z.string(), z.unknown()),
    is_active: z.boolean(),
    data_freshness_seconds: z.number().nullish(),
    url: z.string().nullish(),
    ui_url: z.string().nullish(),
    created_at: z.string(),
    updated_at: z.string(),
    is_materialized: z.boolean(),
    current_version: z.number().optional(),
    versions_count: z.number().optional(),
    materialization: MaterializationStatus.nullish(),
})

export type Endpoint = z.infer<typeof Endpoint>

export const InsightVariable = z.looseObject({
    id: z.string(),
    name: z.string(),
    code_name: z.string(),
    type: z.string(),
    default_value: z.unknown().optional(),
})

export type InsightVariable = z.infer<typeof InsightVariable>

const VARIABLE_REFERENCE = /\{variables\.([a-zA-Z_][a-zA-Z0-9_]*)\}/g

// The HogQL text of a file: the `query` string, or the `query` field of a HogQL query definition.
export function hogqlOf(file: EndpointFile): string {
    const fromDefinition = file.query_definition?.query
    return file.query ?? (typeof fromDefinition === 'string' ? fromDefinition : '')
}

export function variableReferences(query: string): string[] {
    return [...new Set(Array.from(query.matchAll(VARIABLE_REFERENCE), (match) => match[1]!))]
}

export function remoteHogql(endpoint: Endpoint): string {
    return typeof endpoint.query.query === 'string' ? endpoint.query.query : ''
}

// A variable's value on the endpoint, by code name.
export function remoteVariableValues(endpoint: Endpoint): Map<string, unknown> {
    const variables = (endpoint.query.variables ?? {}) as Record<string, { code_name?: unknown; value?: unknown }>
    return new Map(
        Object.values(variables)
            .filter((variable) => typeof variable.code_name === 'string')
            .map((variable) => [variable.code_name as string, variable.value])
    )
}

// posthog-cli writes the lowercase type it infers from a default. PostHog only accepts its own type names.
const API_VARIABLE_TYPES: Record<string, string> = {
    string: 'String',
    integer: 'Number',
    number: 'Number',
    boolean: 'Boolean',
    array: 'List',
    list: 'List',
    date: 'Date',
}

export function apiVariableType(type: string): string {
    return API_VARIABLE_TYPES[type.toLowerCase()] ?? type
}

// A HogQL query can hold settings besides its text, such as `connectionId` or `filters`. A file
// keeps only the text when there are none, so that a push never drops them.
export function isPlainHogql(query: Record<string, unknown>): boolean {
    return (
        query.kind === 'HogQLQuery' &&
        typeof query.query === 'string' &&
        Object.entries(query).every(
            ([key, value]) =>
                ['kind', 'query', 'variables'].includes(key) ||
                value === null ||
                (typeof value === 'object' && Object.keys(value).length === 0)
        )
    )
}

export function remoteVariableNames(endpoint: Endpoint | undefined): string[] {
    return remoteVariableIds(endpoint).map(([name]) => name)
}

// Each variable the query uses, as [code name, project variable ID]. The query keys variables by ID.
export function remoteVariableIds(endpoint: Endpoint | undefined): [string, string][] {
    const variables = endpoint?.query.variables
    if (!variables || typeof variables !== 'object') {
        return []
    }
    return Object.entries(variables as Record<string, { code_name?: unknown }>).flatMap(([id, variable]) =>
        typeof variable.code_name === 'string' ? [[variable.code_name, id] as [string, string]] : []
    )
}

function inferType(value: unknown): string {
    if (typeof value === 'number') {
        return Number.isInteger(value) ? 'integer' : 'number'
    }
    if (typeof value === 'boolean') {
        return 'boolean'
    }
    if (Array.isArray(value)) {
        return 'array'
    }
    return value !== null && typeof value === 'object' ? 'object' : 'string'
}

// Query definitions come back with every optional field set to null. Dropping them keeps pulled
// files short, and PostHog fills the same defaults back in on push.
export function withoutNulls(value: unknown): unknown {
    if (Array.isArray(value)) {
        return value.map(withoutNulls)
    }
    if (value !== null && typeof value === 'object') {
        return Object.fromEntries(
            Object.entries(value)
                .filter(([, child]) => child !== null)
                .map(([key, child]) => [key, withoutNulls(child)])
        )
    }
    return value
}

// `types` maps a variable's code name to its type in the project. Without it, the type comes from the default value.
export function fileFromEndpoint(endpoint: Endpoint, types: ReadonlyMap<string, string> = new Map()): EndpointFile {
    const file: EndpointFile = { name: endpoint.name }
    if (endpoint.description) {
        file.description = endpoint.description
    }
    if (isPlainHogql(endpoint.query) && typeof endpoint.query.query === 'string') {
        file.query = endpoint.query.query.replace(/\r\n?/g, '\n')
    } else {
        const { variables: _variables, ...definition } = endpoint.query
        file.query_definition = withoutNulls(definition) as Record<string, unknown>
    }
    const variables = Object.values((endpoint.query.variables ?? {}) as Record<string, Record<string, unknown>>)
        .filter((variable) => typeof variable.code_name === 'string')
        .map((variable) => ({
            name: variable.code_name as string,
            type: types.get(variable.code_name as string) ?? inferType(variable.value),
            ...(variable.value !== undefined ? { default: variable.value } : {}),
        }))
    if (variables.length > 0) {
        file.variables = variables
    }
    if (endpoint.is_materialized) {
        const schedule = scheduleFor(endpoint.data_freshness_seconds)
        file.materialization = { enabled: true, ...(schedule ? { schedule } : {}) }
    }
    return file
}

export type ResolvedVariables = Map<string, InsightVariable>

// The request body for creating or updating the endpoint a file describes.
export function requestBody(file: EndpointFile, resolved: ResolvedVariables): Record<string, unknown> {
    const query: Record<string, unknown> = file.query_definition
        ? { ...file.query_definition }
        : { kind: 'HogQLQuery', query: file.query }
    const variables = Object.fromEntries(
        (file.variables ?? []).flatMap((variable) => {
            const resolvedVariable = resolved.get(variable.name)
            if (!resolvedVariable) {
                return []
            }
            const entry: Record<string, unknown> = {
                variableId: resolvedVariable.id,
                code_name: resolvedVariable.code_name,
            }
            if (variable.default !== undefined) {
                entry.value = variable.default
                // Without `isNull`, PostHog replaces a null value with the project's default.
                if (variable.default === null) {
                    entry.isNull = true
                }
            }
            return [[resolvedVariable.id, entry]]
        })
    )
    if (Object.keys(variables).length > 0) {
        query.variables = variables
    }
    // PostHog keeps the description when the field is missing, so a file without one sends it empty.
    const body: Record<string, unknown> = { name: file.name, description: file.description ?? '', query }
    // A file without materialization turns it off, or the endpoint would differ from the file forever.
    body.is_materialized = file.materialization?.enabled ?? false
    if (file.materialization?.schedule) {
        body.data_freshness_seconds = SCHEDULES[file.materialization.schedule]
    }
    return body
}

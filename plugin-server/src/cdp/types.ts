import { VMState } from '@posthog/hogvm'
import { DateTime } from 'luxon'

import { HogFlow } from '../schema/hogflow'
import {
    ClickHouseTimestamp,
    ElementPropertyFilter,
    EventPropertyFilter,
    HogQLPropertyFilter,
    PersonPropertyFilter,
    Team,
} from '../types'

export type HogBytecode = any[]

// subset of EntityFilter
export interface HogFunctionFilterBase {
    id: string | null
    name?: string | null
    order?: number
    properties?: (EventPropertyFilter | PersonPropertyFilter | ElementPropertyFilter | HogQLPropertyFilter)[]
}

export interface HogFunctionFilterEvent extends HogFunctionFilterBase {
    type: 'events'
    bytecode?: HogBytecode
}

export interface HogFunctionFilterAction extends HogFunctionFilterBase {
    type: 'actions'
    // Loaded at run time from Action model
    bytecode?: HogBytecode
}

export type HogFunctionFilter = HogFunctionFilterEvent | HogFunctionFilterAction

export type HogFunctionMasking = {
    ttl: number | null
    hash: string
    bytecode: HogBytecode
    threshold: number | null
}

export interface HogFunctionFilters {
    events?: HogFunctionFilterEvent[]
    actions?: HogFunctionFilterAction[]
    filter_test_accounts?: boolean
    bytecode?: HogBytecode
}

export type GroupType = {
    id: string // the "key" of the group
    type: string
    index: number
    url: string
    properties: Record<string, any>
}

export type HogFunctionInvocationGlobals = {
    project: {
        id: number
        name: string
        url: string
    }
    source?: {
        name: string
        url: string
    }
    event: {
        /* Database fields */
        uuid: string
        event: string
        distinct_id: string
        properties: Record<string, unknown>
        elements_chain: string
        timestamp: string

        /* Special fields in Hog */
        url: string
    }
    person?: {
        /** Database fields */
        id: string
        properties: Record<string, any>

        /** Special fields in Hog */
        name: string
        url: string
    }
    groups?: Record<string, GroupType>

    // Unique to sources - will be modified later
    request?: {
        headers: Record<string, string | undefined>
        ip?: string
        body: Record<string, any>
    }
}

export type HogFunctionInvocationGlobalsWithInputs = HogFunctionInvocationGlobals & {
    inputs: Record<string, any>
}

export type HogFunctionFilterGlobals = {
    // Filter Hog is built in the same way as analytics so the global object is meant to be an event
    event: string
    timestamp: string
    elements_chain: string
    elements_chain_href: string
    elements_chain_texts: string[]
    elements_chain_ids: string[]
    elements_chain_elements: string[]
    properties: Record<string, any>
    distinct_id: string

    person: {
        id: string
        properties: Record<string, any>
    } | null
    pdi: {
        distinct_id: string
        person_id: string
        person: {
            id: string
            properties: Record<string, any>
        }
    } | null

    // Used by groupId filters on event_metadata
    $group_0: string | null
    $group_1: string | null
    $group_2: string | null
    $group_3: string | null
    $group_4: string | null

    // Used by group property filters
    group_0: {
        properties: Record<string, any>
    }
    group_1: {
        properties: Record<string, any>
    }
    group_2: {
        properties: Record<string, any>
    }
    group_3: {
        properties: Record<string, any>
    }
    group_4: {
        properties: Record<string, any>
    }
}

export type MetricLogSource = 'hog_function' | 'hog_flow'

export type LogEntryLevel = 'debug' | 'info' | 'warn' | 'error'

export type MinimalLogEntry = {
    timestamp: DateTime
    level: LogEntryLevel
    message: string
}

export type LogEntry = MinimalLogEntry & {
    team_id: number
    log_source: MetricLogSource // The kind of source (hog_function)
    log_source_id: string // The id of the hog function
    instance_id: string // The id of the specific invocation
}

export type LogEntrySerialized = Omit<LogEntry, 'timestamp'> & {
    timestamp: ClickHouseTimestamp
}

export type MinimalAppMetric = {
    team_id: number
    app_source_id: string // The main item (like the hog function or hog flow ID)
    instance_id?: string // The specific instance of the item (can be the invocation ID or a sub item like an action ID)
    metric_kind: 'failure' | 'success' | 'other'
    metric_name:
        | 'succeeded'
        | 'failed'
        | 'filtered'
        | 'disabled_temporarily'
        | 'disabled_permanently'
        | 'masked'
        | 'filtering_failed'
        | 'inputs_failed'
        | 'missing_addon'
        | 'fetch'
        | 'event_triggered_destination'
        | 'destination_invoked'

    count: number
}

export type AppMetricType = MinimalAppMetric & {
    timestamp: ClickHouseTimestamp
    app_source: MetricLogSource
}

export interface HogFunctionTiming {
    kind: 'hog' | 'async_function'
    duration_ms: number
}

export type HogFunctionQueueParametersFetchRequest = {
    type: 'fetch'
    url: string
    method: string
    body?: string
    max_tries?: number
    headers?: Record<string, string>
}

export type CyclotronInvocationQueueParameters = HogFunctionQueueParametersFetchRequest

export const CYCLOTRON_INVOCATION_JOB_QUEUES = ['hog', 'plugin', 'segment', 'hogflow'] as const
export type CyclotronJobQueueKind = (typeof CYCLOTRON_INVOCATION_JOB_QUEUES)[number]

export const CYCLOTRON_JOB_QUEUE_SOURCES = ['postgres', 'kafka'] as const
export type CyclotronJobQueueSource = (typeof CYCLOTRON_JOB_QUEUE_SOURCES)[number]

// Agnostic job invocation type
export type CyclotronJobInvocation = {
    id: string
    teamId: Team['id']
    functionId: string
    state: object | null
    // The queue that the invocation is on
    queue: CyclotronJobQueueKind
    // Optional parameters for that queue to use
    queueParameters?: CyclotronInvocationQueueParameters | null
    // Priority of the invocation
    queuePriority: number
    // When the invocation is scheduled to run
    queueScheduledAt?: DateTime
    // Metadata for the invocation - TODO: check when this gets cleared
    queueMetadata?: Record<string, any> | null
    // Where the invocation came from (kafka or postgres)
    queueSource?: CyclotronJobQueueSource
}

// The result of an execution
export type CyclotronJobInvocationResult<T extends CyclotronJobInvocation = CyclotronJobInvocation> = {
    invocation: T
    finished: boolean
    error?: any
    logs: MinimalLogEntry[]
    metrics: MinimalAppMetric[]
    capturedPostHogEvents: HogFunctionCapturedEvent[]
    execResult?: unknown
}

export type CyclotronJobInvocationHogFunction = CyclotronJobInvocation & {
    state: {
        globals: HogFunctionInvocationGlobalsWithInputs
        vmState?: VMState
        timings: HogFunctionTiming[]
        attempts: number // Indicates the number of times this invocation has been attempted (for example if it gets scheduled for retries)
    }
    hogFunction: HogFunctionType
}

export type CyclotronJobInvocationHogFlow = CyclotronJobInvocation & {
    state?: HogFlowInvocationContext
    hogFlow: HogFlow
}

export type HogFlowInvocationContext = {
    event: HogFunctionInvocationGlobals['event']
    personId?: string
    variables?: Record<string, any>
    currentAction?: {
        id: string
        startedAtTimestamp: number
    }
    actionStepCount?: number
}

// Mostly copied from frontend types
export type HogFunctionInputSchemaType = {
    type:
        | 'string'
        | 'number'
        | 'boolean'
        | 'dictionary'
        | 'choice'
        | 'json'
        | 'integration'
        | 'integration_field'
        | 'email'
    key: string
    label?: string
    choices?: { value: string; label: string }[]
    required?: boolean
    default?: any
    secret?: boolean
    hidden?: boolean
    description?: string
    integration?: string
    integration_key?: string
    requires_field?: string
    integration_field?: string
    requiredScopes?: string
    templating?: boolean
}

export type HogFunctionTypeType = 'destination' | 'transformation' | 'internal_destination' | 'source_webhook'

export interface HogFunctionMappingType {
    inputs_schema?: HogFunctionInputSchemaType[]
    inputs?: Record<string, HogFunctionInputType> | null
    filters?: HogFunctionFilters | null
}

export type HogFunctionType = {
    id: string
    type: HogFunctionTypeType
    team_id: number
    name: string
    enabled: boolean
    deleted: boolean
    hog: string
    bytecode: HogBytecode
    inputs_schema?: HogFunctionInputSchemaType[]
    inputs?: Record<string, HogFunctionInputType | null>
    encrypted_inputs?: Record<string, HogFunctionInputType>
    filters?: HogFunctionFilters | null
    mappings?: HogFunctionMappingType[] | null
    masking?: HogFunctionMasking | null
    depends_on_integration_ids?: Set<IntegrationType['id']>
    is_addon_required: boolean
    template_id?: string
    execution_order?: number
    created_at: string
    updated_at: string
}

export type HogFunctionInputType = {
    value: any
    templating?: 'hog' | 'liquid'
    secret?: boolean
    bytecode?: HogBytecode | object
    order?: number
}

export type IntegrationType = {
    id: number
    team_id: number
    kind: 'slack'
    config: Record<string, any>
    sensitive_config: Record<string, any>

    // Fields we don't load but need for seeding data
    errors?: string
    created_at?: string
    created_by_id?: number
}

export type HogFunctionCapturedEvent = {
    team_id: number
    event: string
    distinct_id: string
    timestamp: string
    properties: Record<string, any>
}

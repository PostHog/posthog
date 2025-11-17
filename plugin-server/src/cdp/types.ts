import { DateTime } from 'luxon'

import { VMState } from '@posthog/hogvm'

import { CyclotronInputType, CyclotronInvocationQueueParametersType } from '~/schema/cyclotron'

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
    source?: 'events' | 'person-updates' // Special case to identify what kind of thing this filters on
    events?: HogFunctionFilterEvent[]
    actions?: HogFunctionFilterAction[]
    properties?: Record<string, any>[] // Global property filters that apply to all events
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

export type CyclotronPerson = {
    id: string
    properties: Record<string, any>
    name: string
    url: string
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
    person?: CyclotronPerson
    groups?: Record<string, GroupType>

    // Unique to sources - will be modified later
    request?: {
        method: string
        headers: Record<string, string | undefined>
        query: Record<string, string | undefined>
        ip?: string
        body: Record<string, any>
        stringBody: string
    }

    unsubscribe_url?: string // For email actions, the unsubscribe URL to use

    actions?: HogFunctionInvocationActionVariables
    variables?: Record<string, any> // For HogFlows, workflow-level variables
}

/**
 * A map of key value variables that persist across actions in a flow
 * These variables can be used to store loop state or pass data between actions
 *
 * Action's can read and write to these variables. Any value stored in the variables
 * map must be JSON serializable, and limited to 1KB in size.
 *
 * After execution, every action will have a corresponding entry in the map with
 * the key `$action/{actionId}` containing the result of the action.
 */
export type HogFunctionInvocationActionVariables = {
    [key: string]: { result: any; error?: any }
}

export type HogFunctionInvocationGlobalsWithInputs = HogFunctionInvocationGlobals & {
    inputs: Record<string, any>
}

export type HogFunctionFilterGlobals = {
    // Filter Hog is built in the same way as analytics so the global object is meant to be an event
    event: string
    uuid: string
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
    metric_kind: 'failure' | 'success' | 'other' | 'email' | 'billing'
    metric_name:
        | 'early_exit'
        | 'triggered'
        | 'trigger_failed'
        | 'succeeded'
        | 'failed'
        | 'filtered'
        | 'disabled_temporarily'
        | 'disabled_permanently'
        | 'rate_limited'
        | 'masked'
        | 'filtering_failed'
        | 'inputs_failed'
        | 'missing_addon'
        | 'fetch'
        | 'billable_invocation'
        | 'dropped'
        | 'email_sent'
        | 'email_failed'
        | 'email_opened'
        | 'email_link_clicked'
        | 'email_bounced'
        | 'email_blocked'
        | 'email_spam'
        | 'email_unsubscribed'
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

// IMPORTANT: All queue names should be lowercase and only [A-Z0-9] characters are allowed.
export const CYCLOTRON_INVOCATION_JOB_QUEUES = [
    'hog',
    'hogoverflow',
    'hogflow',
    'delay10m',
    'delay60m',
    'delay24h',
] as const
export type CyclotronJobQueueKind = (typeof CYCLOTRON_INVOCATION_JOB_QUEUES)[number]

export const CYCLOTRON_JOB_QUEUE_SOURCES = ['postgres', 'kafka', 'delay'] as const
export type CyclotronJobQueueSource = (typeof CYCLOTRON_JOB_QUEUE_SOURCES)[number]

// Agnostic job invocation type
export type CyclotronJobInvocation = {
    id: string
    teamId: Team['id']
    functionId: string
    state: Record<string, any> | null
    // The queue that the invocation is on
    queue: CyclotronJobQueueKind
    // Optional parameters for that queue to use
    queueParameters?: CyclotronInvocationQueueParametersType | null
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

export type CyclotronJobInvocationHogFunctionContext = {
    globals: HogFunctionInvocationGlobalsWithInputs
    vmState?: VMState
    timings: HogFunctionTiming[]
    attempts: number // Indicates the number of times this invocation has been attempted (for example if it gets scheduled for retries)
}

export type CyclotronJobInvocationHogFunction = CyclotronJobInvocation & {
    state: CyclotronJobInvocationHogFunctionContext
    hogFunction: HogFunctionType
}

export type CyclotronJobInvocationHogFlow = CyclotronJobInvocation & {
    state?: HogFlowInvocationContext
    hogFlow: HogFlow
    person?: CyclotronPerson
    filterGlobals: HogFunctionFilterGlobals
}

export type HogFlowInvocationContext = {
    event: HogFunctionInvocationGlobals['event']
    actionStepCount: number
    currentAction?: {
        id: string
        startedAtTimestamp: number
        hogFunctionState?: CyclotronJobInvocationHogFunctionContext
    }
    variables?: Record<string, any>
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
        | 'native_email'
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
    /**
     * templating: true indicates the field supports templating. Alternatively
     * it can be set to 'hog' or 'liquid' to specify the default templating engine to use.
     */
    templating?: boolean | 'hog' | 'liquid'
}

export type HogFunctionTypeType =
    | 'destination'
    | 'transformation'
    | 'internal_destination'
    | 'source_webhook'
    | 'site_destination'

export interface HogFunctionMappingType {
    inputs_schema?: HogFunctionInputSchemaType[]
    inputs?: Record<string, CyclotronInputType> | null
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
    inputs?: Record<string, CyclotronInputType | null>
    encrypted_inputs?: Record<string, CyclotronInputType>
    filters?: HogFunctionFilters | null
    mappings?: HogFunctionMappingType[] | null
    masking?: HogFunctionMasking | null
    template_id?: string
    execution_order?: number
    created_at: string
    updated_at: string
}

export type HogFunctionMappingTemplate = HogFunctionMappingType & {
    name: string
    include_by_default?: boolean
}

export type HogFunctionTemplate = {
    status: 'stable' | 'alpha' | 'beta' | 'deprecated' | 'coming_soon' | 'hidden'
    free: boolean
    type: HogFunctionTypeType
    id: string
    name: string
    description: string
    code: string
    inputs_schema: HogFunctionInputSchemaType[]
    category: string[]
    filters?: HogFunctionFilters
    mappings?: HogFunctionMappingType[]
    mapping_templates?: HogFunctionMappingTemplate[]
    masking?: HogFunctionMasking
    icon_url?: string
    code_language: 'javascript' | 'hog'
}

export type HogFunctionTemplateCompiled = HogFunctionTemplate & {
    bytecode: HogBytecode
}

// Slightly different model from the DB
export type DBHogFunctionTemplate = {
    id: string
    template_id: string
    sha: string
    name: string
    inputs_schema: HogFunctionInputSchemaType[]
    bytecode: HogBytecode
    type: HogFunctionTypeType
    free: boolean
}

export type IntegrationType = {
    id: number
    team_id: number
    kind: 'slack' | 'email' | 'oauth'
    config: Record<string, any>
    sensitive_config: Record<string, any>
}

export type HogFunctionCapturedEvent = {
    team_id: number
    event: string
    distinct_id: string
    timestamp: string
    properties: Record<string, any>
}

export type Response = {
    status: number
    data: any
    content: string
    headers: Record<string, any>
}

export type NativeTemplate = Omit<HogFunctionTemplate, 'code' | 'code_language'> & {
    perform: (
        request: (
            url: string,
            options: {
                method?: 'POST' | 'GET' | 'PATCH' | 'PUT' | 'DELETE'
                headers: Record<string, any>
                json?: any
                body?: string | URLSearchParams
                throwHttpErrors?: boolean
                searchParams?: Record<string, any>
            }
        ) => Promise<Response>,
        inputs: Record<string, any>
    ) => Promise<any> | any
}

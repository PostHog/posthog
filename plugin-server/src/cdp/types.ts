import { VMState } from '@posthog/hogvm'
import { DateTime } from 'luxon'

import {
    AppMetric2Type,
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

    person?: {
        id: string
        properties: Record<string, any>
    }
    pdi?: {
        distinct_id: string
        person_id: string
        person: {
            id: string
            properties: Record<string, any>
        }
    }

    group_0?: {
        properties: Record<string, any>
    }
    group_1?: {
        properties: Record<string, any>
    }
    group_2?: {
        properties: Record<string, any>
    }
    group_3?: {
        properties: Record<string, any>
    }
    group_4?: {
        properties: Record<string, any>
    }
}

export type HogFunctionLogEntrySource = 'system' | 'hog' | 'console'
export type LogEntryLevel = 'debug' | 'info' | 'warn' | 'error'

export type LogEntry = {
    timestamp: DateTime
    level: LogEntryLevel
    message: string
}

export type HogFunctionInvocationLogEntry = LogEntry & {
    team_id: number
    log_source: string // The kind of source (hog_function)
    log_source_id: string // The id of the hog function
    instance_id: string // The id of the specific invocation
}

export type HogFunctionLogEntrySerialized = Omit<HogFunctionInvocationLogEntry, 'timestamp'> & {
    timestamp: ClickHouseTimestamp
}

export interface HogFunctionTiming {
    kind: 'hog' | 'async_function'
    duration_ms: number
}

export type HogFunctionQueueParametersFetchRequest = {
    url: string
    method: string
    body?: string
    return_queue: string
    max_tries?: number
    headers?: Record<string, string>
}

export type CyclotronFetchFailureKind =
    | 'timeout'
    | 'timeoutgettingbody'
    | 'missingparameters'
    | 'invalidparameters'
    | 'requesterror'
    | 'failurestatus'
    | 'invalidbody'
    | 'responsetoolarge'

export type CyclotronFetchFailureInfo = {
    kind: CyclotronFetchFailureKind
    message: string
    headers?: Record<string, string>
    status?: number
    timestamp: DateTime
}

export type HogFunctionQueueParametersFetchResponse = {
    /** An error message to indicate something went wrong and the invocation should be stopped */
    error?: any
    /** On success, the fetch worker returns only the successful response */
    response?: {
        status: number
        headers: Record<string, string>
    } | null
    /** On failure, the fetch worker returns a list of info about the attempts made*/
    trace?: CyclotronFetchFailureInfo[]
    body?: string | null // Both results AND failures can have a body
    timings?: HogFunctionTiming[]
    logs?: LogEntry[]
}

export type HogFunctionInvocationQueueParameters =
    | HogFunctionQueueParametersFetchRequest
    | HogFunctionQueueParametersFetchResponse

export const HOG_FUNCTION_INVOCATION_JOB_QUEUES = ['hog', 'fetch', 'plugin', 'segment'] as const
export type HogFunctionInvocationJobQueue = (typeof HOG_FUNCTION_INVOCATION_JOB_QUEUES)[number]

export const CYCLOTRON_JOB_QUEUE_KINDS = ['postgres', 'kafka'] as const
export type CyclotronJobQueueKind = (typeof CYCLOTRON_JOB_QUEUE_KINDS)[number]

export type HogFunctionInvocation = {
    id: string
    globals: HogFunctionInvocationGlobalsWithInputs
    teamId: Team['id']
    hogFunction: HogFunctionType
    // The current vmstate (set if the invocation is paused)
    vmState?: VMState
    timings: HogFunctionTiming[]
    // Params specific to the queueing system
    queue: HogFunctionInvocationJobQueue
    queueParameters?: HogFunctionInvocationQueueParameters | null
    queuePriority: number
    queueScheduledAt?: DateTime
    queueMetadata?: Record<string, any> | null
    queueSource?: CyclotronJobQueueKind
}

export type HogFunctionAsyncFunctionRequest = {
    name: string
    args: any[]
}

// The result of an execution
export type HogFunctionInvocationResult = {
    invocation: HogFunctionInvocation
    finished: boolean
    error?: any
    logs: LogEntry[]
    metrics: HogFunctionAppMetric[]
    capturedPostHogEvents: HogFunctionCapturedEvent[]
    execResult?: unknown
}

export type HogFunctionInvocationAsyncRequest = {
    state: string // Serialized HogFunctionInvocation without the asyncFunctionRequest
    teamId: number
    hogFunctionId: HogFunctionType['id']
    asyncFunctionRequest?: HogFunctionAsyncFunctionRequest
}

export type HogHooksFetchResponse = {
    state: string // Serialized HogFunctionInvocation
    teamId: number
    hogFunctionId: HogFunctionType['id']
    asyncFunctionResponse: HogFunctionQueueParametersFetchResponse
}

export type HogFunctionInvocationSerialized = Omit<HogFunctionInvocation, 'hogFunction'> & {
    // When serialized to kafka / cyclotron we only store the ID
    hogFunctionId: HogFunctionType['id']
}

// Mostly copied from frontend types
export type HogFunctionInputSchemaType = {
    type: 'string' | 'boolean' | 'dictionary' | 'choice' | 'json' | 'integration' | 'integration_field' | 'email'
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

export type HogFunctionTypeType =
    | 'destination'
    | 'transformation'
    | 'internal_destination'
    | 'source_webhook'
    | 'email'
    | 'sms'
    | 'push'
    | 'activity'
    | 'alert'
    | 'broadcast'

export type HogFunctionKind = 'messaging_campaign'

export interface HogFunctionMappingType {
    inputs_schema?: HogFunctionInputSchemaType[]
    inputs?: Record<string, HogFunctionInputType> | null
    filters?: HogFunctionFilters | null
}

export type HogFunctionType = {
    id: string
    type: HogFunctionTypeType
    kind?: HogFunctionKind | null
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
    template_id?: string
    execution_order?: number
    created_at: string
    updated_at: string
}

export type HogFunctionInputType = {
    value: any
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
export type HogFunctionAppMetric = Pick<
    AppMetric2Type,
    'team_id' | 'app_source_id' | 'metric_kind' | 'metric_name' | 'count'
>

export type HogFunctionMessageToProduce = {
    topic: string
    value: HogFunctionLogEntrySerialized | HogHooksFetchResponse | AppMetric2Type
    key: string
}

export type HogFunctionCapturedEvent = {
    team_id: number
    event: string
    distinct_id: string
    timestamp: string
    properties: Record<string, any>
}

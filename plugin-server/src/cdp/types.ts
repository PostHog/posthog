import { VMState } from '@posthog/hogvm'
import { DateTime } from 'luxon'

import {
    AppMetric2Type,
    ClickHouseTimestamp,
    ElementPropertyFilter,
    EventPropertyFilter,
    PersonPropertyFilter,
    Team,
} from '../types'

export type HogBytecode = any[]

// subset of EntityFilter
export interface HogFunctionFilterBase {
    id: string
    name: string | null
    order: number
    properties: (EventPropertyFilter | PersonPropertyFilter | ElementPropertyFilter)[]
}

export interface HogFunctionFilterEvent extends HogFunctionFilterBase {
    type: 'events'
    bytecode: HogBytecode
}

export interface HogFunctionFilterAction extends HogFunctionFilterBase {
    type: 'actions'
    // Loaded at run time from Action model
    bytecode?: HogBytecode
}

export type HogFunctionFilter = HogFunctionFilterEvent | HogFunctionFilterAction

export type HogFunctionFiltersMasking = {
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

// We have a "parsed" clickhous event type to make it easier to work with calls from kafka as well as those from the frontend
export interface ParsedClickhouseEvent {
    uuid: string
    event: string
    team_id: number
    distinct_id: string
    person_id?: string
    timestamp: string
    created_at: string
    properties: Record<string, any>
    person_created_at?: string
    person_properties: Record<string, any>
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
        uuid: string
        name: string
        distinct_id: string
        properties: Record<string, any>
        timestamp: string
        url: string
    }
    person?: {
        uuid: string
        name: string
        url: string
        properties: Record<string, any>
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
    properties: Record<string, any>

    person?: {
        properties: Record<string, any>
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

export type HogFunctionInvocation = {
    id: string
    globals: HogFunctionInvocationGlobals
    teamId: Team['id']
    hogFunction: HogFunctionType
    queue: 'hog' | 'fetch'
    queueParameters?: Record<string, any>
    // The current vmstate (set if the invocation is paused)
    vmState?: VMState
    timings: HogFunctionTiming[]
}

export type HogFunctionAsyncFunctionRequest = {
    name: string
    args: any[]
}

export type HogFunctionAsyncFunctionResponse = {
    /** An error message to indicate something went wrong and the invocation should be stopped */
    error?: any
    /** The data to be passed to the Hog function from the response */
    response?: {
        status: number
        body: any
    } | null
    timings?: HogFunctionTiming[]
    logs?: LogEntry[]
}

// The result of an execution
export type HogFunctionInvocationResult = {
    invocation: HogFunctionInvocation
    finished: boolean
    error?: any
    // asyncFunctionRequest?: HogFunctionAsyncFunctionRequest
    logs: LogEntry[]
    capturedPostHogEvents?: HogFunctionCapturedEvent[]
}

export type HogFunctionInvocationAsyncRequest = {
    state: string // Serialized HogFunctionInvocation without the asyncFunctionRequest
    teamId: number
    hogFunctionId: HogFunctionType['id']
    asyncFunctionRequest?: HogFunctionAsyncFunctionRequest
}

export type HogFunctionInvocationAsyncResponse = {
    state: string // Serialized HogFunctionInvocation
    teamId: number
    hogFunctionId: HogFunctionType['id']
    asyncFunctionResponse: HogFunctionAsyncFunctionResponse
}

export type HogFunctionInvocationSerialized = {
    state: string // Serialized HogFunctionInvocation
}

// Mostly copied from frontend types
export type HogFunctionInputSchemaType = {
    type: 'string' | 'boolean' | 'dictionary' | 'choice' | 'json' | 'integration' | 'integration_field'
    key: string
    label?: string
    choices?: { value: string; label: string }[]
    required?: boolean
    default?: any
    secret?: boolean
    description?: string
    integration?: string
    integration_key?: string
    integration_field?: 'slack_channel'
}

export type HogFunctionType = {
    id: string
    team_id: number
    name: string
    enabled: boolean
    hog: string
    bytecode: HogBytecode
    inputs_schema?: HogFunctionInputSchemaType[]
    inputs?: Record<string, HogFunctionInputType>
    filters?: HogFunctionFilters | null
    masking?: HogFunctionFiltersMasking | null
    depends_on_integration_ids?: Set<IntegrationType['id']>
}

export type HogFunctionInputType = {
    value: any
    secret?: boolean
    bytecode?: HogBytecode | object
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

export type HogFunctionMessageToProduce = {
    topic: string
    value:
        | HogFunctionLogEntrySerialized
        | HogFunctionInvocationAsyncResponse
        | AppMetric2Type
        | HogFunctionInvocationSerialized
    key: string
}

export type HogFunctionCapturedEvent = {
    team_id: number
    event: string
    distinct_id: string
    timestamp: string
    properties: Record<string, any>
}

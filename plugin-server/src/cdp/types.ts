import { VMState } from '@posthog/hogvm'

import { ElementPropertyFilter, EventPropertyFilter, PersonPropertyFilter } from '../types'

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

export interface HogFunctionFilters {
    events?: HogFunctionFilterEvent[]
    actions?: HogFunctionFilterAction[]
    filter_test_accounts?: boolean
    // Loaded at run time from Team model
    filter_test_accounts_bytecode?: boolean
    bytecode?: HogBytecode
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
    groups?: Record<
        string,
        {
            id: string // the "key" of the group
            type: string
            index: number
            url: string
            properties: Record<string, any>
        }
    >
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
export type HogFunctionLogEntryLevel = 'debug' | 'info' | 'warn' | 'error'

export interface HogFunctionLogEntry {
    team_id: number
    log_source: string // The kind of source (hog_function)
    log_source_id: string // The id of the hog function
    instance_id: string // The id of the specific invocation
    timestamp: string
    level: HogFunctionLogEntryLevel
    message: string
}

export type HogFunctionInvocation = {
    id: string
    globals: HogFunctionInvocationGlobals
}

export type HogFunctionInvocationResult = HogFunctionInvocation & {
    success: boolean
    error?: any
    logs: HogFunctionLogEntry[]
}

export type HogFunctionInvocationAsyncRequest = HogFunctionInvocation & {
    teamId: number
    hogFunctionId: HogFunctionType['id']
    vmState?: VMState
    asyncFunctionName: string // TODO: Type this all more strongly
    asyncFunctionArgs?: any[]
}

export type HogFunctionInvocationAsyncResponse = HogFunctionInvocationAsyncRequest & {
    /** An error message to indicate something went wrong and the invocation should be stopped */
    error?: any
    /** The data to be passed to the Hog function from the response */
    vmResponse?: any
}

// Mostly copied from frontend types
export type HogFunctionInputSchemaType = {
    type: 'string' | 'number' | 'boolean' | 'dictionary' | 'choice' | 'json'
    key: string
    label?: string
    choices?: { value: string; label: string }[]
    required?: boolean
    default?: any
    secret?: boolean
    description?: string
}

export type HogFunctionType = {
    id: string
    team_id: number
    name: string
    enabled: boolean
    hog: string
    bytecode: HogBytecode
    inputs_schema: HogFunctionInputSchemaType[]
    inputs: Record<
        string,
        {
            value: any
            bytecode?: HogBytecode | object
        }
    >
    filters?: HogFunctionFilters | null
}

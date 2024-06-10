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

export type HogFunctionInvocationContext = {
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
        properties: Record<string, any>
        url: string
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

export type HogFunctionInvocation = {
    globals: HogFunctionInvocationContext
}

export type HogFunctionInvocationAsyncRequest = HogFunctionInvocation & {
    hogFunctionId: HogFunctionType['id']
    vmState: VMState
}

export type HogFunctionInvocationAsyncResponse = HogFunctionInvocationAsyncRequest & {
    response: any
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

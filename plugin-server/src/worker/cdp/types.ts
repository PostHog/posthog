import { VMState } from '@posthog/hogvm'

import { PluginConfigFilters } from '../../types'

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
            key: string
            type: string
            index: number
            properties: Record<string, any>
        }
    >
}

export type HogFunctionInvocation = {
    context: HogFunctionInvocationContext
}

export type HogFunctionInvocationAsyncRequest = HogFunctionInvocation & {
    hogFunctionId: HogFunctionType['id']
    state: VMState
}

export type HogFunctionInvocationAsyncResponse = HogFunctionInvocationAsyncRequest & {
    response: any
}

// Mostly copied from frontend types
export type HogFunctionInputSchemaType = {
    type: 'string' | 'number' | 'boolean' | 'dictionary' | 'choice' | 'json'
    name: string
    // label: string
    choices?: { value: string; label: string }[]
    required?: boolean
    // default?: any
    // secret?: boolean
    // description?: string
}

export type HogFunctionType = {
    id: string
    team_id: number
    name: string
    enabled: boolean
    bytecode: any
    inputs: Record<
        string,
        {
            value: any
            bytecode?: any
        }
    >
    filters?: PluginConfigFilters | null
}

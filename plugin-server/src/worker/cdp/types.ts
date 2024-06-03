import { Team } from '../../types'

export type HogFunctionInvocationContext = {
    project: {
        id: number
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
    // metadata: {
    //     topic: string
    //     partition: number
    //     rawSize: number
    //     lowOffset: number
    //     highOffset: number
    //     timestamp: number
    // }

    context: HogFunctionInvocationContext
    team: Team
}

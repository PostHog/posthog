import { ActorType } from '~/types'

export interface RetentionTablePayload {
    date: string
    label: string
    people_url: string
    values: Record<string, any>[]
}

export interface RetentionTrendPayload {
    count: number
    data: number[]
    days: string[]
    labels: string[]
    index: number
}

export interface RetentionTablePeoplePayload {
    next?: string // Legacy support
    offset?: number // Offset for HogQL queries
    result?: RetentionTableAppearanceType[] // TODO: Rename to plural responses to match HogQL responses
    missing_persons?: number
}

export interface RetentionTableAppearanceType {
    person: ActorType
    appearances: number[]
}

import { Dayjs } from 'lib/dayjs'

import { ActorType } from '~/types'

export interface ProcessedRetentionValue {
    count: number
    percentage: number
    cellDate: Dayjs
    isCurrentPeriod: boolean
    isFuture: boolean
}

export interface ProcessedRetentionPayload {
    date: string
    label: string
    people_url: string
    values: ProcessedRetentionValue[]
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

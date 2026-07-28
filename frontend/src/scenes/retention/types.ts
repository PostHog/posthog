import { Dayjs } from 'lib/dayjs'

import { ActorType } from '~/types'

export const NO_BREAKDOWN_VALUE = '$$__posthog_...__$$'

export interface ProcessedRetentionValue {
    count: number
    label: string
    percentage: number
    cellDate: Dayjs
    isCurrentPeriod: boolean
    isFuture: boolean
    aggregation_value?: number
}

export interface ProcessedRetentionPayload {
    date: Dayjs
    label: string
    people_url: string
    values: ProcessedRetentionValue[]
    breakdown_value?: string | number | null
    /** The result's breakdown_value as returned by the query, before any display mapping
     * (e.g. the raw "other" sentinel). Used to match dashboard breakdown color configs. */
    rawBreakdownValue?: string | number | null
}

export interface RetentionTableRow {
    label: string
    cohortSize: number
    values: ProcessedRetentionValue[]
    breakdown_value?: string | number | null
}

export interface RetentionTrendPayload {
    count: number
    data: number[]
    days: string[]
    labels: string[]
    index: number
    breakdown_value?: string | number | null
    /** Set only when the series represents a single breakdown value (mean-per-breakdown and
     * breakdown interval views). Unlike breakdown_value, which holds the display label there,
     * this keeps the raw value so dashboard breakdown color configs can match it. */
    rawBreakdownValue?: string | number | null
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

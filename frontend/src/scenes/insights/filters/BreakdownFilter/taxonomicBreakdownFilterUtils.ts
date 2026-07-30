import { MultipleBreakdownType } from '~/queries/schema/schema-general'
import { BreakdownType } from '~/types'

export const isAllCohort = (t: number | string): t is string => typeof t === 'string' && t == 'all'

export const isCohort = (t: number | string): t is number => typeof t === 'number'

export const isCohortBreakdown = (t: number | string): t is number | string => isAllCohort(t) || isCohort(t)

export const isURLNormalizeable = (propertyName: string): boolean => {
    return ['$current_url', '$pathname'].includes(propertyName)
}

export function isMultipleBreakdownType(breakdownType?: BreakdownType | null): breakdownType is MultipleBreakdownType {
    const types: MultipleBreakdownType[] = [
        'person',
        'event',
        'event_metadata',
        'group',
        'session',
        'hogql',
        'data_warehouse',
    ]
    return !!breakdownType && (types as string[]).includes(breakdownType)
}

// Not every taxonomic/property filter type is a valid breakdown type. Casting one straight to
// `BreakdownType` lets an unsupported value (e.g. a legacy `"property"`) reach the query, where the
// backend rejects it with a dead-end error. Guard the value against the enum instead of casting.
export function isBreakdownType(breakdownType?: string | null): breakdownType is BreakdownType {
    const types: BreakdownType[] = [
        'cohort',
        'person',
        'event',
        'event_metadata',
        'group',
        'session',
        'hogql',
        'data_warehouse',
        'data_warehouse_person_property',
        'revenue_analytics',
    ]
    return !!breakdownType && (types as string[]).includes(breakdownType)
}

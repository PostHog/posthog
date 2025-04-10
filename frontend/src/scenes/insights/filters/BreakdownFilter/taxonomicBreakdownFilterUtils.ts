import { MultipleBreakdownType } from '~/queries/schema/schema-general'
import { BreakdownType } from '~/types'

export const isAllCohort = (t: number | string): t is string => typeof t === 'string' && t == 'all'

export const isCohort = (t: number | string): t is number => typeof t === 'number'

export const isCohortBreakdown = (t: number | string): t is number | string => isAllCohort(t) || isCohort(t)

export const isURLNormalizeable = (propertyName: string): boolean => {
    return ['$current_url', '$pathname'].includes(propertyName)
}

export function isMultipleBreakdownType(breakdownType?: BreakdownType | null): breakdownType is MultipleBreakdownType {
    const types: MultipleBreakdownType[] = ['person', 'event', 'event_metadata', 'group', 'session', 'hogql']
    return !!breakdownType && (types as string[]).includes(breakdownType)
}

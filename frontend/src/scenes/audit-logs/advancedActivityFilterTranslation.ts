import { CyclotronJobFilterPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import { AdvancedActivityLogFilters, DEFAULT_START_DATE, DetailFilter } from './advancedActivityLogsLogic'

const WHITELISTED_DETAIL_PATHS = new Set(['name', 'changes'])

const operationToOperator = (operation: DetailFilter['operation']): PropertyOperator => {
    switch (operation) {
        case 'in':
            return PropertyOperator.In
        case 'contains':
            return PropertyOperator.IContains
        case 'exact':
        default:
            return PropertyOperator.Exact
    }
}

export interface AdvancedActivityTranslationResult {
    properties: CyclotronJobFilterPropertyFilter[]
    droppedFields: string[]
}

export function advancedActivityFiltersToHogProperties(
    filters: AdvancedActivityLogFilters
): AdvancedActivityTranslationResult {
    const properties: CyclotronJobFilterPropertyFilter[] = []
    const droppedFields: string[] = []

    if (filters.scopes && filters.scopes.length > 0) {
        properties.push({
            key: 'scope',
            type: PropertyFilterType.Event,
            value: filters.scopes as string[],
            operator: PropertyOperator.Exact,
        })
    }

    if (filters.activities && filters.activities.length > 0) {
        properties.push({
            key: 'activity',
            type: PropertyFilterType.Event,
            value: filters.activities,
            operator: PropertyOperator.Exact,
        })
    }

    if (filters.item_ids && filters.item_ids.length > 0) {
        properties.push({
            key: 'item_id',
            type: PropertyFilterType.Event,
            value: filters.item_ids,
            operator: PropertyOperator.Exact,
        })
    }

    if (filters.was_impersonated !== undefined) {
        properties.push({
            key: 'was_impersonated',
            type: PropertyFilterType.Event,
            value: [String(filters.was_impersonated)],
            operator: PropertyOperator.Exact,
        })
    }

    if (filters.is_system !== undefined) {
        properties.push({
            key: 'is_system',
            type: PropertyFilterType.Event,
            value: [String(filters.is_system)],
            operator: PropertyOperator.Exact,
        })
    }

    if (filters.detail_filters) {
        for (const [path, detail] of Object.entries(filters.detail_filters)) {
            if (WHITELISTED_DETAIL_PATHS.has(path)) {
                properties.push({
                    key: `detail.${path}`,
                    type: PropertyFilterType.Event,
                    value: detail.value,
                    operator: operationToOperator(detail.operation),
                })
            } else {
                droppedFields.push(`detail.${path}`)
            }
        }
    }

    if (filters.users && filters.users.length > 0) {
        droppedFields.push('users')
    }

    const hasCustomStart = !!filters.start_date && filters.start_date !== DEFAULT_START_DATE
    if (hasCustomStart || filters.end_date) {
        droppedFields.push('date range')
    }

    return { properties, droppedFields }
}

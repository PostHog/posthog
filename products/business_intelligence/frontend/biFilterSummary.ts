import { BIConfig, BIFilter, BIResultFilter } from '~/queries/schema/schema-business-intelligence'

import {
    getBIFieldPillLabel,
    getBIFilterSummary,
    getBIValuePillLabel,
    isBIFilterActive,
    resultAsRowFilter,
} from './biEditorTypes'
import { buildBIConditionExpression, normalizeBIConditionGroup } from './biFilterGroups'
import { createBIMemberLabelLookup } from './biMemberAliases'

export function getBIFilterLabel(filter: BIFilter): string {
    return filter.label?.trim() || getBIFieldPillLabel(filter.field)
}

export function getBIResultFilterLabel(config: BIConfig, filter: BIResultFilter): string {
    return (
        filter.label?.trim() ||
        (config.values[filter.measureIndex] ? getBIValuePillLabel(config.values[filter.measureIndex]) : 'Count of rows')
    )
}

export function describeBIFilter(
    filter: BIFilter,
    config: BIConfig,
    memberLabel = createBIMemberLabelLookup(config)
): string {
    if (filter.operator === 'in' || filter.operator === 'not_in') {
        return `${filter.operator === 'in' ? 'is one of' : 'is not one of'} ${(filter.values ?? []).map((value) => JSON.stringify(memberLabel(filter.field, value))).join(', ')}`
    }
    return getBIFilterSummary(
        filter.operator === 'equals' || filter.operator === 'not_equals'
            ? { ...filter, value: filter.value ? memberLabel(filter.field, filter.value) : filter.value }
            : filter
    )
}

export function getBIActiveFilterSummary(config: BIConfig): { rows: string | null; results: string | null } {
    const memberLabel = createBIMemberLabelLookup(config)
    const rows = buildBIConditionExpression(
        normalizeBIConditionGroup(
            config.rowFilterGroup,
            config.filters.map((filter) => filter.field.id)
        ),
        new Map(
            config.filters.map((filter) => [
                filter.field.id,
                isBIFilterActive(filter)
                    ? `${getBIFilterLabel(filter)}: ${describeBIFilter(filter, config, memberLabel)}`
                    : null,
            ])
        )
    )
    const resultFilters = config.resultFilters ?? []
    const results = buildBIConditionExpression(
        normalizeBIConditionGroup(
            config.resultFilterGroup,
            resultFilters.map((filter) => filter.id)
        ),
        new Map(
            resultFilters.map((filter) => {
                const row = resultAsRowFilter(config, filter)
                return [
                    filter.id,
                    row && isBIFilterActive(row)
                        ? `${getBIResultFilterLabel(config, filter)}: ${describeBIFilter(row, config, memberLabel)}`
                        : null,
                ]
            })
        )
    )
    return { rows, results }
}

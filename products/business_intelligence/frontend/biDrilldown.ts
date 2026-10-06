import { dayjs } from 'lib/dayjs'

import { BIConfig, BIFilter, BIVisualizationNode } from '~/queries/schema/schema-business-intelligence'
import {
    DashboardFilter,
    DataVisualizationNode,
    HogQLVariable,
    VisualizationNode,
    NodeKind,
} from '~/queries/schema/schema-general'
import { escapeHogQLString } from '~/queries/utils'
import { ChartDisplayType } from '~/types'

import { BI_COMPARISON_EMPTY_LABEL, getBIComparisonDateExpression } from './biComparison'
import {
    buildBIQuery,
    buildBIRowsQuery,
    buildBITopMembership,
    fieldExpression,
    getBIResultDimensions,
} from './biEditorTypes'

export interface BIDrillSelection {
    filters: BIFilter[]
    previous: boolean
    labels: { name: string; value: string }[]
}

export function getBIEffectiveQuery(
    node: VisualizationNode,
    override?: DashboardFilter | null,
    variablesOverride?: Record<string, HogQLVariable> | null
): VisualizationNode {
    const filters = { ...node.source.filters }
    if (override?.date_from || override?.date_to) {
        filters.dateRange = {
            date_from: override.date_from,
            date_to: override.date_to,
            explicitDate: !!override.explicitDate,
        }
    }
    if (override?.properties?.length) {
        filters.properties = [...(filters.properties ?? []), ...override.properties]
    }
    if (override?.filterTestAccounts != null) {
        filters.filterTestAccounts = override.filterTestAccounts
    }
    if (override?.interval != null) {
        filters.interval = override.interval
    }
    if (override?.breakdown_filter != null) {
        filters.breakdownFilter = override.breakdown_filter
    }
    const variables = node.source.variables ? { ...node.source.variables } : undefined
    for (const [id, variable] of Object.entries(variablesOverride ?? {})) {
        if (variables?.[id]) {
            variables[id] = { ...variables[id], value: variable.value, isNull: variable.isNull }
        }
    }
    return { ...node, source: { ...node.source, filters, variables } }
}

export function getBIDrillSelection(config: BIConfig, record: Record<string, unknown>): BIDrillSelection {
    const period = String(record.bi_comparison ?? '')
    const previous = /^(Previous|Comparison) period(?: · |$)/.test(period)
    const dimensions = getBIResultDimensions(config)
    const filters: BIFilter[] = []
    const labels: BIDrillSelection['labels'] = []
    for (const { field, column, position } of dimensions) {
        if (!(column in record)) {
            continue
        }
        let value = record[column]
        if (position !== undefined) {
            try {
                const values: unknown = typeof value === 'string' ? JSON.parse(value) : value
                if (!Array.isArray(values) || position >= values.length) {
                    continue
                }
                value = values[position]
            } catch {
                continue
            }
        }
        if (value === undefined) {
            continue
        }
        const displayValue = value
        if (config.totals?.rows || config.totals?.columns || config.totals?.subtotals) {
            if (value === 'Total') {
                continue
            }
            if (typeof value === 'string' && value.startsWith('Total') && value.endsWith(' (category)')) {
                value = value.slice(0, -11)
            }
        }
        const other = field.id === config.topN?.fieldId && config.topN?.includeOther
        let filter: BIFilter
        if (other && value === 'Other') {
            const member = buildBITopMembership(config)
            if (!member) {
                continue
            }
            filter = { field, operator: 'custom', value: '', customExpression: `${member} = false`, enabled: true }
        } else {
            if (other && typeof value === 'string' && value.startsWith('Other') && value.endsWith(' (category)')) {
                value = value.slice(0, -11)
            }
            const shiftedDate = previous && ['date', 'datetime'].includes(field.type)
            const expression = fieldExpression(
                shiftedDate ? { ...field, expression: getBIComparisonDateExpression(field) } : field
            )
            if (value instanceof Date) {
                value = dayjs(value).format('YYYY-MM-DD HH:mm:ss')
            }
            if (typeof value === 'object' && value !== null) {
                continue
            }
            if (typeof value === 'number' && !Number.isFinite(value)) {
                continue
            }
            if (typeof value === 'number' && field.type === 'date') {
                const date = dayjs.unix(value).utc()
                if (!date.isValid()) {
                    continue
                }
                value = date.format('YYYY-MM-DD')
            }
            if (shiftedDate || typeof value === 'boolean') {
                const literal = typeof value === 'boolean' ? String(value) : escapeHogQLString(String(value))
                filter = {
                    field,
                    operator: 'custom',
                    value: '',
                    customExpression: value === null ? `${expression} IS NULL` : `${expression} = ${literal}`,
                    enabled: true,
                }
            } else {
                filter =
                    value === null
                        ? { field, operator: 'is_not_set', value: '', enabled: true }
                        : String(value).trim()
                          ? { field, operator: 'equals', value: String(value), enabled: true }
                          : { field, operator: 'in', value: '', values: [String(value)], enabled: true }
            }
        }
        filters.push(filter)
        labels.push({ name: field.name, value: String(displayValue ?? '(empty)') })
    }
    return { filters, previous, labels }
}

export function getBIChartRecord(
    node: VisualizationNode,
    xColumn: string,
    xValue: unknown,
    breakdown?: string
): Record<string, unknown> {
    const record: Record<string, unknown> = { [xColumn]: xValue }
    const config = node.kind === NodeKind.BIVisualizationNode ? node.config : undefined
    if (breakdown !== undefined && config) {
        const column = node.chartSettings?.seriesBreakdownColumn
        if (column) {
            record[column] = breakdown === '$$_posthog_breakdown_null_$$' ? null : breakdown
        }
        if (config.compareFilter?.compare) {
            record.bi_comparison = breakdown
            const dimension = getBIResultDimensions(config).find((dimension) => dimension.column !== xColumn)
            if (dimension && /^(Current|Previous|Comparison) period · /.test(breakdown)) {
                const category = breakdown.replace(/^(Current|Previous|Comparison) period · /, '')
                record[dimension.column] =
                    category === BI_COMPARISON_EMPTY_LABEL
                        ? null
                        : category.startsWith(BI_COMPARISON_EMPTY_LABEL) && category.endsWith(' (category)')
                          ? category.slice(0, -11)
                          : category
            }
        }
    }
    return record
}

export function getBIDrillQueries(
    node: VisualizationNode,
    selection: BIDrillSelection
): { rows: DataVisualizationNode; worksheet: BIVisualizationNode | null } | null {
    const saved = node.kind === NodeKind.BIVisualizationNode ? node.config : undefined
    if (!saved) {
        return null
    }
    const config: BIConfig = {
        ...saved,
        dateRange: node.source.filters?.dateRange ?? saved.dateRange,
        filters: [...saved.filters, ...selection.filters],
        topN: undefined,
    }
    const source = buildBIRowsQuery(config, selection.previous)
    if (!source) {
        return null
    }
    source.filters = { ...source.filters, ...node.source.filters }
    source.variables = node.source.variables
    const generated = selection.previous ? null : buildBIQuery(config)?.node
    const worksheet: BIVisualizationNode | null = generated
        ? { ...generated, kind: NodeKind.BIVisualizationNode, config }
        : null
    if (worksheet) {
        worksheet.source.filters = source.filters
        worksheet.source.variables = source.variables
    }
    return { rows: { kind: NodeKind.DataVisualizationNode, source, display: ChartDisplayType.ActionsTable }, worksheet }
}

import { getSeriesColor } from 'lib/colors'

import { BIConfig } from '~/queries/schema/schema-business-intelligence'
import { AnyResponseType, ChartAxis, NodeKind, VisualizationNode } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import { hasBIAnalysis } from './biAnalysis'
import { getBIComparisonGroupLimit } from './biComparisonLimit'
import { buildBIQuery, fieldExpression, getBIResultDimensions, getBIResultMeasureColumns } from './biEditorTypes'

export function getBISeriesSettings(query: VisualizationNode, settings: ChartAxis['settings']): ChartAxis['settings'] {
    return query.kind === NodeKind.BIVisualizationNode && query.config.colorBy === null
        ? { ...settings, display: { ...settings?.display, color: getSeriesColor(0) } }
        : settings
}

export function getBIResultSummary(
    query: VisualizationNode,
    response: AnyResponseType | null
): { groups: number | null; marks: number; limited: boolean; possiblyLimited?: boolean } | null {
    const visible = getBIVisualizationResponse(query, response)
    if (
        query.kind !== NodeKind.BIVisualizationNode ||
        !visible ||
        !('results' in visible) ||
        !Array.isArray(visible.results) ||
        !('columns' in visible) ||
        !Array.isArray(visible.columns)
    ) {
        return null
    }
    const columns = visible.columns
    const groupingIndex = columns.indexOf('bi_grouping')
    const rows = visible.results.filter((row) => groupingIndex === -1 || Number(row[groupingIndex]) === 0)
    const dimensions = getBIResultDimensions(query.config).map(({ column }) => columns.indexOf(column))
    const measures = getBIResultMeasureColumns(query.config)
        .map(({ column }) => columns.indexOf(column))
        .filter((index) => index !== -1)
    return {
        groups: dimensions.some((index) => index === -1)
            ? null
            : new Set(rows.map((row) => JSON.stringify(dimensions.map((index) => row[index])))).size,
        marks: rows.reduce(
            (count, row) => count + measures.filter((index) => row[index] !== null && row[index] !== undefined).length,
            0
        ),
        limited: 'hasMore' in visible && visible.hasMore === true,
        ...(query.config.limit === 50000 && visible.results.length >= 50000
            ? { possiblyLimited: !('hasMore' in visible && visible.hasMore === true) }
            : {}),
    }
}

function getBIDataConfig(config: BIConfig): BIConfig {
    return config.rows.length + config.columns.length === 2 &&
        !hasBIAnalysis(config) &&
        !config.compareFilter?.compare &&
        !config.missingDates
        ? { ...config, chartType: ChartDisplayType.ActionsBar }
        : config
}

export function getBIVisualizationSource(query: VisualizationNode): VisualizationNode['source'] {
    if (query.kind !== NodeKind.BIVisualizationNode) {
        return query.source
    }
    const probe = buildBIQuery(getBIDataConfig(query.config), true)
    return probe ? { ...query.source, query: probe.query } : query.source
}

export function getBIVisualizationResponse(
    query: VisualizationNode,
    response: AnyResponseType | null
): AnyResponseType | null {
    if (
        query.kind !== NodeKind.BIVisualizationNode ||
        !response ||
        !('results' in response) ||
        !Array.isArray(response.results)
    ) {
        return response
    }
    const dataConfig = getBIDataConfig(query.config)
    if (dataConfig !== query.config && 'columns' in response && Array.isArray(response.columns)) {
        const dimensions = getBIResultDimensions(query.config)
        const columns = response.columns
        const aliases = new Map<string, string>()
        getBIResultDimensions(dataConfig).forEach(({ column, field }, index) => {
            if (columns[index] === column || columns[index] === fieldExpression(field)) {
                aliases.set(columns[index], dimensions[index].column)
            }
        })
        response = {
            ...response,
            columns: response.columns.map((column) => aliases.get(column) ?? column),
            ...('types' in response && Array.isArray(response.types)
                ? { types: response.types.map(([column, type]) => [aliases.get(column) ?? column, type]) }
                : {}),
        }
    }
    const trimmed = {
        ...response,
        results: response.results.slice(0, query.config.limit),
        hasMore: response.results.length > query.config.limit || ('hasMore' in response && response.hasMore === true),
    }
    if (query.config.compareFilter?.compare) {
        const columns = 'columns' in response && Array.isArray(response.columns) ? response.columns : []
        const dimensions = getBIResultDimensions(query.config).map(({ column }) => columns.indexOf(column))
        if (dimensions.some((index) => index === -1)) {
            return trimmed
        }
        const key = (row: unknown[]): string => JSON.stringify(dimensions.map((index) => row[index]))
        const groups = new Set(response.results.map(key))
        const selected = new Set([...groups].slice(0, getBIComparisonGroupLimit(query.config)))
        return {
            ...response,
            results: response.results.filter((row: unknown[]) => selected.has(key(row))),
            hasMore: groups.size > selected.size || ('hasMore' in response && response.hasMore === true),
        }
    }
    return trimmed
}

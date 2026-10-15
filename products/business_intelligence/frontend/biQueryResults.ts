import { getSeriesColor } from 'lib/colors'

import { AnyResponseType, ChartAxis, NodeKind, VisualizationNode } from '~/queries/schema/schema-general'

import { getBIComparisonGroupLimit } from './biComparisonLimit'
import { buildBIQuery, getBIResultDimensions, getBIResultMeasureColumns } from './biEditorTypes'

export function getBISeriesSettings(query: VisualizationNode, settings: ChartAxis['settings']): ChartAxis['settings'] {
    return query.kind === NodeKind.BIVisualizationNode && query.config.colorBy === null
        ? { ...settings, display: { ...settings?.display, color: getSeriesColor(0) } }
        : settings
}

export function getBIResultSummary(
    query: VisualizationNode,
    response: AnyResponseType | null
): { groups: number; marks: number; limited: boolean } | null {
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
        groups: new Set(rows.map((row) => JSON.stringify(dimensions.map((index) => row[index])))).size,
        marks: rows.reduce(
            (count, row) => count + measures.filter((index) => row[index] !== null && row[index] !== undefined).length,
            0
        ),
        limited: 'hasMore' in visible && visible.hasMore === true,
    }
}

export function getBIVisualizationSource(query: VisualizationNode): VisualizationNode['source'] {
    if (query.kind !== NodeKind.BIVisualizationNode) {
        return query.source
    }
    const probe = buildBIQuery(query.config, true)
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
    if (query.config.compareFilter?.compare) {
        const columns = 'columns' in response && Array.isArray(response.columns) ? response.columns : []
        const dimensions = getBIResultDimensions(query.config).map(({ column }) => columns.indexOf(column))
        const key = (row: unknown[]): string => JSON.stringify(dimensions.map((index) => row[index]))
        const groups = new Set(response.results.map(key))
        const selected = new Set([...groups].slice(0, getBIComparisonGroupLimit(query.config)))
        return {
            ...response,
            results: response.results.filter((row) => selected.has(key(row))),
            hasMore: groups.size > selected.size || ('hasMore' in response && response.hasMore === true),
        }
    }
    return {
        ...response,
        results: response.results.slice(0, query.config.limit),
        hasMore: response.results.length > query.config.limit || ('hasMore' in response && response.hasMore === true),
    }
}

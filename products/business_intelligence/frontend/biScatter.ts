import { getSeriesColor } from 'lib/colors'

import { SqlScatterSeries } from '~/queries/nodes/DataVisualization/Components/Charts/sqlScatterGraphAdapter'
import { AxisSeries } from '~/queries/nodes/DataVisualization/dataVisualizationLogic'
import { BIConfig, BIVisualizationNode } from '~/queries/schema/schema-business-intelligence'

import { getBIDrillSelection } from './biDrilldown'
import {
    getBIFieldPillLabel,
    getBIResultDimensions,
    getBIResultMeasureColumns,
    getBIValuePillLabel,
    isNumericBIResultField,
} from './biEditorTypes'
import { isBIConditionGroup, normalizeBIConditionGroup } from './biFilterGroups'
import { createBIMemberLabelLookup } from './biMemberAliases'

export function getBIScatterAxisOptions(config: BIConfig): { value: string; label: string }[] {
    return [
        ...getBIResultDimensions(config)
            .filter(({ field }) => isNumericBIResultField(field))
            .map(({ column, field }) => ({ value: column, label: getBIFieldPillLabel(field) })),
        ...getBIResultMeasureColumns(config).map(({ column, value }) => ({
            value: column,
            label: value ? getBIValuePillLabel(value) : 'Count of rows',
        })),
    ]
}

export function createBIScatterRowKey(config: BIConfig, columns: string[]): (row: unknown[]) => string {
    const indices = getBIResultDimensions(config).map(({ column }) => columns.indexOf(column))
    return (row) => JSON.stringify(indices.map((index) => row[index]))
}

export function getBIScatterRowKey(config: BIConfig, columns: string[], row: unknown[]): string {
    return createBIScatterRowKey(config, columns)(row)
}

function scatterCoordinate(value: unknown, logarithmic: boolean): number | null {
    if (value === null || value === undefined || value === '') {
        return null
    }
    const coordinate = Number(value)
    return Number.isFinite(coordinate) && (!logarithmic || coordinate > 0) ? coordinate : null
}

export function buildBIScatterSeries(
    query: BIVisualizationNode,
    columns: string[],
    rows: unknown[][],
    xData: AxisSeries<string> | null,
    yData: AxisSeries<number | null>[]
): SqlScatterSeries[] | null {
    if (!xData) {
        return []
    }
    const dimensions = getBIResultDimensions(query.config)
    const colorDimension = dimensions.find(({ field }) => field.id === query.config.colorBy)
    const colorColumn = colorDimension?.column
    const colorIndex = colorColumn ? columns.indexOf(colorColumn) : -1
    const xCoordinates = rows.map((_, index) =>
        scatterCoordinate(xData.data[index], query.chartSettings?.scatter?.xScale === 'logarithmic')
    )
    const logarithmicY = query.chartSettings?.leftYAxisSettings?.scale === 'logarithmic'
    const seriesKey = (measure: AxisSeries<number | null>, row: unknown[]): string =>
        JSON.stringify([measure.column.name, colorIndex < 0 ? null : JSON.stringify(row[colorIndex] ?? null)])
    const seriesKeys = new Set<string>()
    let pointCount = 0
    for (const measure of yData) {
        for (const [index, row] of rows.entries()) {
            if (xCoordinates[index] === null || scatterCoordinate(measure.data[index], logarithmicY) === null) {
                continue
            }
            seriesKeys.add(seriesKey(measure, row))
            pointCount++
            if (seriesKeys.size > 100 || seriesKeys.size * pointCount > 1_000_000) {
                return null
            }
        }
    }
    const memberLabel = createBIMemberLabelLookup(query.config)
    const indexedDimensions = dimensions.map(({ field, column }) => ({ field, index: columns.indexOf(column) }))
    const rowKeys = rows.map((row) => JSON.stringify(indexedDimensions.map(({ index }) => row[index])))
    const rowLabels = rows.map(
        (row) =>
            indexedDimensions
                .map(({ field, index }) => `${getBIFieldPillLabel(field)}: ${memberLabel(field, row[index])}`)
                .join(' · ') || 'All matching rows'
    )
    const output = new Map<string, SqlScatterSeries>()
    for (const [measureIndex, measure] of yData.entries()) {
        rows.forEach((row, rowIndex) => {
            const x = xCoordinates[rowIndex]
            const y = scatterCoordinate(measure.data[rowIndex], logarithmicY)
            if (x === null || y === null) {
                return
            }
            const category = colorIndex < 0 ? undefined : row[colorIndex]
            const categoryKey = JSON.stringify(category ?? null)
            const key = seriesKey(measure, row)
            if (!output.has(key)) {
                const hash = [...categoryKey].reduce(
                    (hash, character) => (Math.imul(hash, 31) + character.charCodeAt(0)) >>> 0,
                    0
                )
                output.set(key, {
                    key,
                    label:
                        colorIndex < 0
                            ? measure.settings?.display?.label || measure.column.name
                            : memberLabel(colorDimension!.field, category),
                    color:
                        query.config.colorBy === null
                            ? getSeriesColor(0)
                            : colorIndex < 0
                              ? measure.settings?.display?.color || getSeriesColor(measureIndex)
                              : getSeriesColor(hash),
                    points: [],
                })
            }
            output.get(key)!.points.push({
                x,
                y,
                label: rowLabels[rowIndex],
                meta: { settings: measure.settings, rowIndex, rowKey: rowKeys[rowIndex] },
            })
        })
    }
    return [...output.values()].sort((a, b) => a.key.localeCompare(b.key))
}

export function keepBIScatterRows(config: BIConfig, records: Record<string, unknown>[]): BIConfig | null {
    const dimensionCount = getBIResultDimensions(config).length
    if (!records.length || records.length > 200 || !dimensionCount) {
        return null
    }
    const selections = records.map((record) => getBIDrillSelection(config, record))
    if (selections.some((selection) => selection.filters.length !== dimensionCount)) {
        return null
    }
    const filters = [...config.filters]
    const used = new Set(filters.map((filter) => filter.field.id))
    const selectedGroups = selections.map((selection) => {
        const ids = selection!.filters.map((filter) => {
            let id = `selection:${filter.field.id}`
            while (used.has(id)) {
                id += ':'
            }
            used.add(id)
            filters.push({
                ...filter,
                field: {
                    ...filter.field,
                    id,
                    localFieldId:
                        filter.field.localFieldId ?? (filter.field.localDefinition ? filter.field.id : undefined),
                },
            })
            return id
        })
        return { operator: 'AND' as const, filters: ids, groups: [] }
    })
    const original = normalizeBIConditionGroup(
        config.rowFilterGroup,
        config.filters.map((filter) => filter.field.id)
    )
    const rowFilterGroup = {
        operator: 'AND' as const,
        filters: [],
        groups: [original, { operator: 'OR' as const, filters: [], groups: selectedGroups }],
    }
    return isBIConditionGroup(rowFilterGroup) ? { ...config, filters, rowFilterGroup } : null
}

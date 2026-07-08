import type { ChartTemplateDef, InstantiateContext } from 'flint-chart/core'

import type { LineChartConfig, Series } from '@posthog/quill-charts'

import {
    buildCategoryAlignedData,
    extractCategories,
    formatTemporalLabel,
    groupBy,
    makeTickFormatter,
    temporalSortValue,
} from '../template-utils'
import type { QuillLineChartSpec } from '../types'

const isDiscrete = (type: string | undefined): boolean => type === 'nominal' || type === 'ordinal'

/** Quill line charts position points by label index (a band domain), so a
 *  continuous or temporal x collapses onto its ordered distinct values — one
 *  label per distinct x. Even spacing is exact for the regular time grids
 *  agents chart; a truly irregular x-axis is a known limitation of this backend. */
function buildXDomain(
    table: Record<string, unknown>[],
    xField: string,
    xType: string | undefined,
    ordinalSortOrder?: string[],
    temporalFormat?: string
): { labels: string[]; keyOf: (row: Record<string, unknown>) => string } {
    if (isDiscrete(xType)) {
        return {
            labels: extractCategories(table, xField, ordinalSortOrder),
            keyOf: (row) => String(row[xField] ?? ''),
        }
    }
    const isTemporal = xType === 'temporal'
    const distinct = new Map<string, number>()
    for (const row of table) {
        const raw = row[xField]
        if (raw == null) {
            continue
        }
        const sortVal = isTemporal ? temporalSortValue(raw) : Number(raw)
        if (Number.isFinite(sortVal) && !distinct.has(String(raw))) {
            distinct.set(String(raw), sortVal)
        }
    }
    const orderedRaw = [...distinct.entries()].sort((a, b) => a[1] - b[1]).map(([raw]) => raw)
    const labelOf = (raw: string): string => (isTemporal ? formatTemporalLabel(raw, temporalFormat) : raw)
    return {
        labels: orderedRaw.map(labelOf),
        keyOf: (row) => labelOf(String(row[xField] ?? '')),
    }
}

function instantiateLine(area: boolean, spec: Record<string, unknown>, ctx: InstantiateContext): void {
    const { channelSemantics, table } = ctx
    const xCS = channelSemantics.x
    const yCS = channelSemantics.y
    if (!xCS?.field || !yCS?.field) {
        return
    }

    const domain = buildXDomain(table, xCS.field, xCS.type, xCS.ordinalSortOrder, xCS.temporalFormat)
    // Re-key rows onto the label domain so category alignment works for
    // discrete, temporal, and quantitative x alike
    const keyed = table.map((row) => ({ ...row, __flint_x: domain.keyOf(row) }))

    const colorField = channelSemantics.color?.field
    const fill: Series['fill'] | undefined = area ? { opacity: 0.4 } : undefined

    let series: Series[]
    if (colorField) {
        series = [...groupBy(keyed, colorField).entries()].map(([name, rows]) => ({
            key: name,
            label: name,
            data: buildCategoryAlignedData(rows, '__flint_x', yCS.field, domain.labels),
            fill,
        }))
    } else {
        series = [
            {
                key: yCS.field,
                label: yCS.field,
                data: buildCategoryAlignedData(keyed, '__flint_x', yCS.field, domain.labels),
                fill,
            },
        ]
    }

    const interpolate = ctx.chartProperties?.interpolate
    const config: LineChartConfig = {
        showGrid: true,
        curve: interpolate === 'monotone' || interpolate === 'basis' ? 'monotone' : 'linear',
        // Flint's zero decision: zero !== false means the axis includes 0
        floatBaseline: yCS.zero?.zero === false,
        yTickFormatter: makeTickFormatter(yCS.format),
        xAxisLabel: xCS.field,
        yAxisLabel: yCS.field,
        legend: { show: series.length > 1 },
    }

    const assembled: Pick<QuillLineChartSpec, 'component' | 'series' | 'labels' | 'config'> = {
        component: 'LineChart',
        series,
        labels: domain.labels,
        config,
    }
    Object.assign(spec, assembled)
    delete spec.mark
    delete spec.encoding
}

export const quillLineChartDef: ChartTemplateDef = {
    chart: 'Line Chart',
    template: { mark: 'line', encoding: {} },
    channels: ['x', 'y', 'color'],
    markCognitiveChannel: 'position',
    declareLayoutMode: () => ({
        paramOverrides: { continuousMarkCrossSection: { x: 100, y: 20, seriesCountAxis: 'auto' } },
    }),
    instantiate: (spec, ctx) => instantiateLine(false, spec, ctx),
}

export const quillAreaChartDef: ChartTemplateDef = {
    chart: 'Area Chart',
    template: { mark: 'area', encoding: {} },
    channels: ['x', 'y', 'color'],
    markCognitiveChannel: 'area',
    declareLayoutMode: () => ({
        paramOverrides: { continuousMarkCrossSection: { x: 100, y: 20, seriesCountAxis: 'auto' } },
    }),
    // Multiple filled series auto-stack in quill's LineChart, matching Flint's
    // stacked-by-default Area Chart semantics
    instantiate: (spec, ctx) => instantiateLine(true, spec, ctx),
}

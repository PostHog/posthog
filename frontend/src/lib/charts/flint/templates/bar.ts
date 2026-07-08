import type { ChartTemplateDef, InstantiateContext } from 'flint-chart/core'

import type { Series } from '@posthog/quill-charts'
import type { BarChartConfig } from '@posthog/quill-charts'

import { buildCategoryAlignedData, detectAxes, extractCategories, groupBy, makeTickFormatter } from '../template-utils'
import type { QuillBarChartSpec } from '../types'

function declareBandedCategoryAxis(
    channelSemantics: Parameters<NonNullable<ChartTemplateDef['declareLayoutMode']>>[0]
): ReturnType<NonNullable<ChartTemplateDef['declareLayoutMode']>> {
    const { categoryAxis } = detectAxes(channelSemantics)
    return { axisFlags: { [categoryAxis]: { banded: true } } }
}

function instantiateBar(
    barLayout: 'grouped' | 'stacked',
    spec: Record<string, unknown>,
    ctx: InstantiateContext
): void {
    const { channelSemantics, table } = ctx
    const { categoryAxis, valueAxis } = detectAxes(channelSemantics)
    const catCS = channelSemantics[categoryAxis]
    const valCS = channelSemantics[valueAxis]
    if (!catCS?.field || !valCS?.field) {
        return
    }

    const categories = extractCategories(table, catCS.field, catCS.ordinalSortOrder)
    const colorField = channelSemantics.color?.field

    let series: Series[]
    if (colorField && colorField !== catCS.field) {
        series = [...groupBy(table, colorField).entries()].map(([name, rows]) => ({
            key: name,
            label: name,
            data: buildCategoryAlignedData(rows, catCS.field, valCS.field, categories),
        }))
    } else {
        series = [
            {
                key: valCS.field,
                label: valCS.field,
                data: buildCategoryAlignedData(table, catCS.field, valCS.field, categories),
            },
        ]
    }

    const horizontal = categoryAxis === 'y'
    const valueFormatter = makeTickFormatter(valCS.format)
    const config: BarChartConfig = {
        barLayout,
        axisOrientation: horizontal ? 'horizontal' : 'vertical',
        showGrid: true,
        barCornerRadius: typeof ctx.chartProperties?.cornerRadius === 'number' ? ctx.chartProperties.cornerRadius : 0,
        // Quill's value axis is y for vertical bars and x for horizontal ones,
        // but yTickFormatter always formats the value axis
        yTickFormatter: valueFormatter,
        xAxisLabel: horizontal ? valCS.field : catCS.field,
        yAxisLabel: horizontal ? catCS.field : valCS.field,
        legend: { show: series.length > 1 },
    }

    const assembled: Pick<QuillBarChartSpec, 'component' | 'series' | 'labels' | 'config'> = {
        component: 'BarChart',
        series,
        labels: categories,
        config,
    }
    Object.assign(spec, assembled)
    delete spec.mark
    delete spec.encoding
}

export const quillBarChartDef: ChartTemplateDef = {
    chart: 'Bar Chart',
    template: { mark: 'bar', encoding: {} },
    channels: ['x', 'y', 'color'],
    markCognitiveChannel: 'length',
    declareLayoutMode: declareBandedCategoryAxis,
    instantiate: (spec, ctx) => instantiateBar('grouped', spec, ctx),
}

export const quillGroupedBarChartDef: ChartTemplateDef = {
    chart: 'Grouped Bar Chart',
    template: { mark: 'bar', encoding: {} },
    channels: ['x', 'y', 'color'],
    markCognitiveChannel: 'length',
    declareLayoutMode: declareBandedCategoryAxis,
    instantiate: (spec, ctx) => instantiateBar('grouped', spec, ctx),
}

export const quillStackedBarChartDef: ChartTemplateDef = {
    chart: 'Stacked Bar Chart',
    template: { mark: 'bar', encoding: {} },
    channels: ['x', 'y', 'color'],
    markCognitiveChannel: 'length',
    declareLayoutMode: declareBandedCategoryAxis,
    instantiate: (spec, ctx) => instantiateBar('stacked', spec, ctx),
}

import type { ChartTemplateDef, InstantiateContext } from 'flint-chart/core'

import type { PieChartConfig, Series } from '@posthog/quill-charts'

import { extractCategories } from '../template-utils'
import type { QuillPieChartSpec } from '../types'

/** Slice values per category: sum of the size measure, or row counts when no
 *  size channel is bound (same fallback as Flint's other backends). */
function computeSlices(ctx: InstantiateContext): { label: string; value: number }[] {
    const { channelSemantics, table } = ctx
    const colorField = channelSemantics.color?.field
    const sizeField = channelSemantics.size?.field
    if (!colorField) {
        return []
    }

    const totals = new Map<string, number>()
    for (const row of table) {
        const cat = String(row[colorField] ?? '')
        const val = sizeField ? Number(row[sizeField]) || 0 : 1
        totals.set(cat, (totals.get(cat) ?? 0) + val)
    }
    const categories = extractCategories(table, colorField, channelSemantics.color?.ordinalSortOrder)
    return categories.map((cat) => ({ label: cat, value: totals.get(cat) ?? 0 }))
}

function instantiatePie(innerRadiusRatio: number, spec: Record<string, unknown>, ctx: InstantiateContext): void {
    let slices = computeSlices(ctx)
    if (slices.length === 0) {
        return
    }

    const sortSlices = ctx.chartProperties?.sortSlices
    if (sortSlices === 'descending' || sortSlices === 'ascending') {
        slices = [...slices].sort((a, b) => (sortSlices === 'descending' ? b.value - a.value : a.value - b.value))
    }

    // Quill pie charts take one Series per slice; the slice value defaults to
    // the sum of the series' data
    const series: Series[] = slices.map((s) => ({ key: s.label, label: s.label, data: [s.value] }))
    const config: PieChartConfig = {
        innerRadiusRatio,
        showValueOnSlice: true,
    }

    const assembled: Pick<QuillPieChartSpec, 'component' | 'series' | 'config'> = {
        component: 'PieChart',
        series,
        config,
    }
    Object.assign(spec, assembled)
    delete spec.mark
    delete spec.encoding
}

export const quillPieChartDef: ChartTemplateDef = {
    chart: 'Pie Chart',
    template: { mark: 'arc', encoding: {} },
    channels: ['size', 'color'],
    markCognitiveChannel: 'area',
    instantiate: (spec, ctx) => instantiatePie(0, spec, ctx),
}

export const quillDoughnutChartDef: ChartTemplateDef = {
    chart: 'Doughnut Chart',
    template: { mark: 'arc', encoding: {} },
    channels: ['size', 'color'],
    markCognitiveChannel: 'area',
    instantiate: (spec, ctx) => instantiatePie(0.5, spec, ctx),
}

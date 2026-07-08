import type {
    AssembleOptions,
    ChartAssemblyInput,
    ChartEncoding,
    ChartWarning,
    InstantiateContext,
    LayoutDeclaration,
} from 'flint-chart/core'
import {
    applyEncodingOverrides,
    computeChannelBudgets,
    computeLayout,
    computeZeroDecision,
    convertTemporalData,
    filterOverflow,
    normalizeStaticSeries,
    resolveChannelSemantics,
} from 'flint-chart/core'

import { applyAggregation } from './aggregate'
import { quillGetTemplateDef, quillTemplateDefs } from './templates'
import type { QuillChartSpec } from './types'

// Defaults mirroring flint-chart's internal resolveBaseSize/deriveStretchCaps
// (not exported from flint-chart/core)
const DEFAULT_BASE_SIZE = { width: 400, height: 320 }
const DEFAULT_MAX_STRETCH = 1.5

const FACET_CHANNELS = ['column', 'row'] as const

/**
 * Assemble a quill-charts spec from a Flint chart input.
 *
 * The quill analog of flint-chart's `assembleVegaLite` / `assembleECharts` /
 * `assembleChartjs`: Flint's compiler frontend (semantic resolution) and
 * optimizer (overflow + layout) run unchanged from `flint-chart/core`; only
 * the Stage 3 code generator differs, emitting quill component props instead
 * of a rendering-library config. Colors and pixel-level layout are left to
 * quill, which themes from CSS variables and computes its own layout — only
 * Flint's semantic decisions (sort order, zero baseline, formatting, series
 * routing, overflow truncation) carry through.
 *
 * Not supported (yet): faceting (`column`/`row` are ignored with a warning),
 * named-view pivots, and chart types quill has no component for — see
 * `quillTemplateDefs` for what is.
 */
export function assembleQuill(input: ChartAssemblyInput): QuillChartSpec {
    const chartType = input.chart_spec.chartType
    const chartTemplate = quillGetTemplateDef(chartType)
    if (!chartTemplate) {
        const available = quillTemplateDefs.map((t) => t.chart).join(', ')
        throw new Error(`Unknown quill chart type: ${chartType}. Available types: ${available}`)
    }
    if (!input.data.values) {
        throw new Error('The quill backend requires inline data (`data.values`); `data.url` is not supported')
    }

    const semanticTypes = input.semantic_types ?? {}
    const chartProperties = input.chart_spec.chartProperties
    const sizeCeiling = input.chart_spec.canvasSize
    const specBase = input.chart_spec.baseSize ?? DEFAULT_BASE_SIZE
    const baseSize = sizeCeiling
        ? { width: Math.min(specBase.width, sizeCeiling.width), height: Math.min(specBase.height, sizeCeiling.height) }
        : { ...specBase }

    const warnings: ChartWarning[] = []

    // ── PRE-PHASE: static series normalization + facet stripping ──
    const normalized = normalizeStaticSeries(input.chart_spec.encodings, input.data.values, semanticTypes)
    let data = normalized.data
    const rawEncodings: Record<string, ChartEncoding> = { ...normalized.encodings }
    for (const channel of FACET_CHANNELS) {
        if (rawEncodings[channel]) {
            warnings.push({
                severity: 'warning',
                code: 'facet-unsupported',
                message: `The quill backend does not support faceting; the '${channel}' encoding was ignored`,
                channel,
            })
            delete rawEncodings[channel]
        }
    }

    const encodings = applyEncodingOverrides(chartTemplate, rawEncodings, chartProperties)
    data = applyAggregation(encodings, data)

    // ── PHASE 0: resolve semantics ──
    const convertedData = convertTemporalData(data, semanticTypes)
    const channelSemantics = resolveChannelSemantics(encodings, data, semanticTypes, convertedData)

    const tplMark = chartTemplate.template?.mark
    const effectiveMarkType = (typeof tplMark === 'string' ? tplMark : tplMark?.type) || 'point'
    for (const [channel, cs] of Object.entries(channelSemantics)) {
        if ((channel === 'x' || channel === 'y') && cs.type === 'quantitative') {
            const numericValues = data
                .map((r: Record<string, unknown>) => r[cs.field])
                .filter((v): v is number => typeof v === 'number' && !isNaN(v))
            cs.zero = computeZeroDecision(cs.semanticAnnotation.semanticType, channel, effectiveMarkType, numericValues)
        }
    }

    // ── STEP 0a: template layout declaration ──
    const declaration: LayoutDeclaration = chartTemplate.declareLayoutMode
        ? chartTemplate.declareLayoutMode(channelSemantics, data, chartProperties)
        : {}

    const options = input.options ?? {}
    const effectiveOptions: AssembleOptions = {
        ...options,
        ...declaration.paramOverrides,
    }
    const maxStretch = effectiveOptions.maxStretch ?? DEFAULT_MAX_STRETCH
    effectiveOptions.maxStretchX = sizeCeiling ? Math.max(1, sizeCeiling.width / baseSize.width) : maxStretch
    effectiveOptions.maxStretchY = sizeCeiling ? Math.max(1, sizeCeiling.height / baseSize.height) : maxStretch

    // ── STEP 0b/0c: budgets + overflow filtering ──
    const budgets = computeChannelBudgets(channelSemantics, declaration, convertedData, baseSize, effectiveOptions)
    const overflowResult = filterOverflow(
        channelSemantics,
        declaration,
        encodings,
        convertedData,
        budgets,
        new Set([effectiveMarkType])
    )
    const values = overflowResult.filteredData
    warnings.push(...overflowResult.warnings)

    // ── PHASE 1: layout ──
    const layoutResult = computeLayout(
        channelSemantics,
        declaration,
        values,
        baseSize,
        effectiveOptions,
        budgets.facetGrid
    )
    layoutResult.truncations = overflowResult.truncations

    // ── PHASE 2: instantiate the quill spec ──
    const resolvedEncodings: Record<string, { field: string; type: string; aggregate?: string }> = {}
    for (const [channel, encoding] of Object.entries(encodings)) {
        const cs = channelSemantics[channel]
        if (cs) {
            resolvedEncodings[channel] = { field: cs.field, type: cs.type, aggregate: encoding.aggregate }
        }
    }

    const instantiateContext: InstantiateContext = {
        channelSemantics,
        layout: layoutResult,
        table: values,
        fullTable: convertedData,
        resolvedEncodings,
        encodings,
        chartProperties,
        staticSeries: normalized.staticSeries,
        canvasSize: baseSize,
        semanticTypes,
        chartType,
        assembleOptions: effectiveOptions,
    }

    const spec: Record<string, unknown> = structuredClone(chartTemplate.template)
    chartTemplate.instantiate(spec, instantiateContext)
    if (!spec.component) {
        throw new Error(
            `Could not assemble a '${chartType}': the encodings did not resolve to the channels the template needs`
        )
    }

    const assembled = spec as unknown as QuillChartSpec
    if (warnings.length > 0) {
        assembled._warnings = warnings
    }
    assembled._width = layoutResult.subplotWidth
    assembled._height = layoutResult.subplotHeight
    assembled._dataLength = values.length
    return assembled
}

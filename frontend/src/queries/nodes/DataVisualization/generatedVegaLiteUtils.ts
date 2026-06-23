import {
    GeneratedVegaLiteChartSettings,
    GeneratedVegaLiteField,
    HogQLQueryResponse,
} from '~/queries/schema/schema-general'

export const DEFAULT_GENERATED_VEGA_LITE_PROMPT = 'Create the best chart suited for this data.'

export const GENERATED_VEGA_LITE_SYSTEM_PROMPT = [
    'Create a clean Vega-Lite visualization for this SQL result.',
    'Use only the provided fields and the named posthog_results data source.',
    'Prefer readable charts, but use richer Vega-Lite marks when they make the data clearer.',
    'Do not include external data, URLs, JavaScript, HTML, transforms, params, selections, projections, or raw Vega.',
    'Return only Vega-Lite JSON.',
].join(' ')

const MAX_SAMPLE_ROWS = 20
const MAX_SAMPLE_VALUES_PER_COLUMN = 10
const MAX_STRING_LENGTH = 200
const MAX_JSON_VALUE_LENGTH = 400
const MAX_SPEC_JSON_LENGTH = 20000
const MAX_TITLE_LENGTH = 200
const MAX_DESCRIPTION_LENGTH = 500
const MIN_VIEW_DIMENSION = 120
const MAX_VIEW_DIMENSION = 2000
const MAX_ARC_RADIUS = 130
const DEFAULT_CHART_PADDING = { top: 24, right: 32, bottom: 56, left: 64 }
const DEFAULT_ARC_CHART_PADDING = { top: 24, right: 32, bottom: 72, left: 32 }
const VEGA_LITE_SCHEMA = 'https://vega.github.io/schema/vega-lite/v6.json'
const SUPPORTED_VEGA_LITE_SCHEMAS = new Set([VEGA_LITE_SCHEMA, 'https://vega.github.io/schema/vega-lite/v5.json'])
export const POSTHOG_RESULTS_DATASET = 'posthog_results'
export const GENERATED_VEGA_LITE_VIEW_ATTR = 'generated-vega-lite-visualization'

export type SQLVisualizationSemanticType = 'temporal' | 'quantitative' | 'nominal' | 'ordinal'

export interface SQLVisualizationGenerationColumn {
    name: string
    type: string | null
    semanticType?: SQLVisualizationSemanticType
    sampleValues: unknown[]
    nullCount?: number
    distinctSampleCount?: number
}

export type SQLVisualizationGenerationField = GeneratedVegaLiteField

export interface SQLVisualizationGenerationRequest {
    query: string
    prompt: string
    columns: SQLVisualizationGenerationColumn[]
    fields: SQLVisualizationGenerationField[]
    sampleRows: Record<string, unknown>[]
    rowCount: number
    view?: SQLVisualizationGenerationView
}

export type ValidatedVegaLiteSpec = Record<string, unknown>

export interface SQLVisualizationGenerationView {
    width: number
    height: number
}

export interface VegaLiteValidationResult {
    spec: ValidatedVegaLiteSpec
    warnings: string[]
}

export interface BuildSQLVisualizationGenerationRequestOptions {
    view?: SQLVisualizationGenerationView
}

export type { GeneratedVegaLiteChartSettings }

type PlainObject = Record<string, unknown>

export class VegaLiteValidationError extends Error {
    constructor(message: string) {
        super(message)
        this.name = 'VegaLiteValidationError'
    }
}

const isPlainObject = (value: unknown): value is PlainObject =>
    typeof value === 'object' && value !== null && !Array.isArray(value)

const truncateString = (value: string, maxLength: number = MAX_STRING_LENGTH): string => {
    if (value.length <= maxLength) {
        return value
    }

    return `${value.slice(0, maxLength)}...`
}

const clampViewDimension = (value: number, fallback: number): number => {
    if (!Number.isFinite(value) || value <= 0) {
        return fallback
    }

    return Math.round(Math.min(Math.max(value, MIN_VIEW_DIMENSION), MAX_VIEW_DIMENSION))
}

const dimensionsFromElement = (element: HTMLElement | null | undefined): SQLVisualizationGenerationView | null => {
    if (!element) {
        return null
    }

    const rect = element.getBoundingClientRect()
    if (rect.width <= 0 || rect.height <= 0) {
        return null
    }

    return {
        width: clampViewDimension(rect.width, 800),
        height: clampViewDimension(rect.height, 420),
    }
}

export const getGeneratedVegaLiteViewDimensions = (element?: HTMLElement | null): SQLVisualizationGenerationView => {
    const elementDimensions = dimensionsFromElement(element)
    if (elementDimensions) {
        return elementDimensions
    }

    if (typeof document !== 'undefined') {
        const chartElement = document.querySelector<HTMLElement>(`[data-attr="${GENERATED_VEGA_LITE_VIEW_ATTR}"]`)
        const chartDimensions = dimensionsFromElement(chartElement)
        if (chartDimensions) {
            return chartDimensions
        }
    }

    if (typeof window !== 'undefined') {
        return {
            width: clampViewDimension(window.innerWidth - 480, 800),
            height: clampViewDimension(window.innerHeight - 320, 420),
        }
    }

    return { width: 800, height: 420 }
}

const compactValue = (value: unknown): unknown => {
    if (value === null || value === undefined) {
        return null
    }

    if (typeof value === 'string') {
        return truncateString(value)
    }

    if (typeof value === 'number') {
        return Number.isFinite(value) ? value : String(value)
    }

    if (typeof value === 'boolean') {
        return value
    }

    if (value instanceof Date) {
        return value.toISOString()
    }

    try {
        return truncateString(JSON.stringify(value), MAX_JSON_VALUE_LENGTH)
    } catch {
        return String(value)
    }
}

const getResponseRows = (response: HogQLQueryResponse): unknown[][] => {
    if (Array.isArray(response.results)) {
        return response.results as unknown[][]
    }

    return []
}

const getColumnType = (response: HogQLQueryResponse, index: number): string | null => {
    const typeRow = Array.isArray(response.types) ? response.types[index] : null
    if (Array.isArray(typeRow) && typeof typeRow[1] === 'string') {
        return typeRow[1]
    }

    return null
}

const inferSemanticType = (type: string | null): SQLVisualizationSemanticType => {
    if (!type) {
        return 'nominal'
    }

    if (/Date/i.test(type)) {
        return 'temporal'
    }

    if (/(Int|Float|Decimal|UInt)/i.test(type)) {
        return 'quantitative'
    }

    return 'nominal'
}

const slugifyFieldName = (sourceColumn: string, index: number, usedNames: Set<string>): string => {
    const base = sourceColumn
        .trim()
        .replace(/[^A-Za-z0-9_]+/g, '_')
        .replace(/^_+|_+$/g, '')
        .slice(0, 64)
    const normalizedBase = /^[A-Za-z_][A-Za-z0-9_]*$/.test(base) ? base : `field_${index}`
    let field = normalizedBase || `field_${index}`

    if (usedNames.has(field)) {
        field = `field_${index}`
    }

    while (usedNames.has(field)) {
        field = `${field}_${usedNames.size}`
    }

    usedNames.add(field)
    return field
}

export const buildSQLVisualizationGenerationRequest = (
    query: string,
    prompt: string,
    response: HogQLQueryResponse,
    options: BuildSQLVisualizationGenerationRequestOptions = {}
): SQLVisualizationGenerationRequest => {
    const columns = Array.isArray(response.columns) ? response.columns.map((column) => String(column)) : []
    const rows = getResponseRows(response)
    const usedFieldNames = new Set<string>()
    const fields: SQLVisualizationGenerationField[] = columns.map((column, index) => {
        const type = getColumnType(response, index)

        return {
            field: slugifyFieldName(column, index, usedFieldNames),
            sourceColumn: column,
            label: column,
            type,
            semanticType: inferSemanticType(type),
        }
    })

    const sampleRows = rows.slice(0, MAX_SAMPLE_ROWS).map((row) => {
        const sampleRow: Record<string, unknown> = {}
        fields.forEach((field, index) => {
            sampleRow[field.field] = compactValue(row[index])
        })
        return sampleRow
    })

    const generationColumns = fields.map((field, index): SQLVisualizationGenerationColumn => {
        const values = rows.slice(0, MAX_SAMPLE_ROWS).map((row) => compactValue(row[index]))
        const sampleValues: unknown[] = []
        const seenValues = new Set<string>()
        let nullCount = 0

        values.forEach((value) => {
            if (value === null) {
                nullCount += 1
                return
            }

            const serializedValue = JSON.stringify(value)
            if (!seenValues.has(serializedValue) && sampleValues.length < MAX_SAMPLE_VALUES_PER_COLUMN) {
                seenValues.add(serializedValue)
                sampleValues.push(value)
            }
        })

        return {
            name: field.sourceColumn,
            type: field.type ?? null,
            semanticType: field.semanticType,
            sampleValues,
            nullCount,
            distinctSampleCount: seenValues.size,
        }
    })

    return {
        query,
        prompt,
        columns: generationColumns,
        fields,
        sampleRows,
        rowCount: rows.length,
        view: options.view,
    }
}

export const buildVegaLiteDataRows = (
    response: HogQLQueryResponse,
    fields: SQLVisualizationGenerationField[]
): Record<string, unknown>[] => {
    return getResponseRows(response).map((row) => {
        const mappedRow: Record<string, unknown> = {}
        fields.forEach((field, index) => {
            mappedRow[field.field] = compactValue(row[index])
        })
        return mappedRow
    })
}

const assertSafeString = (value: string, path: string, maxLength: number = MAX_TITLE_LENGTH): void => {
    if (value.length > maxLength) {
        throw new VegaLiteValidationError(`String at ${path} is too long.`)
    }

    if (/(<[^>]+>|javascript:|data:|https?:\/\/)/i.test(value)) {
        throw new VegaLiteValidationError(`Unsafe string at ${path}.`)
    }
}

const blockedVegaLiteKeys = new Set([
    'bind',
    'calculate',
    'datasets',
    'events',
    'expr',
    'filter',
    'href',
    'init',
    'lookup',
    'on',
    'params',
    'projection',
    'select',
    'selection',
    'signal',
    'signals',
    'transform',
    'update',
    'url',
])

const removeUnsupportedKeys = (
    object: PlainObject,
    allowedKeys: Set<string>,
    path: string,
    warnings: string[]
): void => {
    Object.keys(object).forEach((key) => {
        if (blockedVegaLiteKeys.has(key)) {
            throw new VegaLiteValidationError(`Unsupported key "${key}" at ${path}.`)
        }

        if (!allowedKeys.has(key)) {
            delete object[key]
            warnings.push(`Removed unsupported key "${key}" at ${path}.`)
        }
    })
}

const assertPrimitiveOrPrimitiveArray = (value: unknown, path: string): void => {
    if (Array.isArray(value)) {
        if (value.length > 100) {
            throw new VegaLiteValidationError(`Array at ${path} is too long.`)
        }
        value.forEach((item, index) => assertPrimitiveOrPrimitiveArray(item, `${path}[${index}]`))
        return
    }

    if (value === null || ['string', 'number', 'boolean'].includes(typeof value)) {
        if (typeof value === 'string') {
            assertSafeString(value, path)
        }
        return
    }

    throw new VegaLiteValidationError(`Unsupported value at ${path}.`)
}

const validateSimpleVegaValue = (value: unknown, path: string, depth: number = 0): void => {
    if (Array.isArray(value)) {
        if (value.length > 100) {
            throw new VegaLiteValidationError(`Array at ${path} is too long.`)
        }
        value.forEach((item, index) => validateSimpleVegaValue(item, `${path}[${index}]`, depth + 1))
        return
    }

    if (isPlainObject(value)) {
        if (depth > 4) {
            throw new VegaLiteValidationError(`Object at ${path} is too deeply nested.`)
        }
        if (Object.keys(value).length > 100) {
            throw new VegaLiteValidationError(`Object at ${path} has too many keys.`)
        }
        Object.entries(value).forEach(([key, nestedValue]) => {
            if (blockedVegaLiteKeys.has(key)) {
                throw new VegaLiteValidationError(`Unsupported key "${key}" at ${path}.`)
            }
            validateSimpleVegaValue(nestedValue, `${path}.${key}`, depth + 1)
        })
        return
    }

    assertPrimitiveOrPrimitiveArray(value, path)
}

const validateDimension = (value: unknown, path: string): void => {
    if (value === 'container') {
        return
    }

    if (isPlainObject(value)) {
        const step = value.step
        if (Object.keys(value).length === 1 && typeof step === 'number' && Number.isFinite(step) && step > 0) {
            return
        }
    }

    if (typeof value === 'number' && Number.isFinite(value) && value > 0 && value <= 2000) {
        return
    }

    throw new VegaLiteValidationError(`Unsupported dimension at ${path}.`)
}

const allowedTopLevelKeys = new Set([
    '$schema',
    'align',
    'autosize',
    'background',
    'bounds',
    'center',
    'columns',
    'concat',
    'title',
    'description',
    'width',
    'height',
    'data',
    'facet',
    'hconcat',
    'layer',
    'mark',
    'padding',
    'encoding',
    'config',
    'resolve',
    'spacing',
    'spec',
    'vconcat',
])
const allowedMarks = new Set([
    'arc',
    'area',
    'bar',
    'boxplot',
    'circle',
    'errorband',
    'errorbar',
    'line',
    'point',
    'rect',
    'rule',
    'square',
    'text',
    'tick',
    'trail',
])
const allowedMarkKeys = new Set([
    'align',
    'angle',
    'baseline',
    'blend',
    'clip',
    'color',
    'continuousBandSize',
    'cornerRadius',
    'cornerRadiusBottomLeft',
    'cornerRadiusBottomRight',
    'cornerRadiusEnd',
    'cornerRadiusTopLeft',
    'cornerRadiusTopRight',
    'discreteBandSize',
    'dx',
    'dy',
    'ellipsis',
    'fill',
    'fillOpacity',
    'filled',
    'font',
    'fontSize',
    'fontStyle',
    'fontWeight',
    'height',
    'innerRadius',
    'interpolate',
    'invalid',
    'lineBreak',
    'lineHeight',
    'limit',
    'opacity',
    'orient',
    'outerRadius',
    'padAngle',
    'point',
    'radius',
    'radius2',
    'size',
    'stroke',
    'interpolate',
    'strokeCap',
    'strokeDash',
    'strokeDashOffset',
    'strokeJoin',
    'strokeMiterLimit',
    'strokeOpacity',
    'strokeWidth',
    'tension',
    'text',
    'theta',
    'theta2',
    'tooltip',
    'type',
    'width',
    'x',
    'x2',
    'y',
    'y2',
])
const allowedEncodingChannels = new Set([
    'angle',
    'color',
    'column',
    'detail',
    'facet',
    'fill',
    'fillOpacity',
    'key',
    'latitude',
    'latitude2',
    'longitude',
    'longitude2',
    'opacity',
    'order',
    'radius',
    'radius2',
    'row',
    'shape',
    'size',
    'stroke',
    'strokeDash',
    'strokeOpacity',
    'strokeWidth',
    'text',
    'theta',
    'theta2',
    'tooltip',
    'x',
    'x2',
    'xError',
    'xError2',
    'xOffset',
    'y',
    'y2',
    'yError',
    'yError2',
    'yOffset',
])
const allowedEncodingKeys = new Set([
    'aggregate',
    'axis',
    'bandPosition',
    'bin',
    'datum',
    'field',
    'format',
    'formatType',
    'header',
    'impute',
    'legend',
    'scale',
    'sort',
    'stack',
    'timeUnit',
    'title',
    'type',
    'value',
])
const allowedEncodingTypes = new Set(['quantitative', 'temporal', 'nominal', 'ordinal'])
const allowedScaleKeys = new Set([
    'base',
    'bins',
    'clamp',
    'constant',
    'domain',
    'domainMax',
    'domainMid',
    'domainMin',
    'exponent',
    'interpolate',
    'nice',
    'padding',
    'paddingInner',
    'paddingOuter',
    'range',
    'reverse',
    'round',
    'scheme',
    'type',
    'zero',
])
const allowedAxisKeys = new Set([
    'aria',
    'bandPosition',
    'description',
    'domain',
    'domainCap',
    'domainColor',
    'domainDash',
    'domainDashOffset',
    'domainOpacity',
    'domainWidth',
    'format',
    'formatType',
    'grid',
    'gridCap',
    'gridColor',
    'gridDash',
    'gridDashOffset',
    'gridOpacity',
    'gridWidth',
    'labelAlign',
    'labelAngle',
    'labelBaseline',
    'labelBound',
    'labelColor',
    'labelExpr',
    'labelFlush',
    'labelFlushOffset',
    'labelFont',
    'labelFontSize',
    'labelFontStyle',
    'labelFontWeight',
    'labelLimit',
    'labelLineHeight',
    'labelOffset',
    'labelOpacity',
    'labelOverlap',
    'labelPadding',
    'labelSeparation',
    'labels',
    'maxExtent',
    'minExtent',
    'offset',
    'orient',
    'position',
    'style',
    'tickBand',
    'tickCap',
    'tickColor',
    'tickCount',
    'tickDash',
    'tickDashOffset',
    'tickExtra',
    'tickMinStep',
    'tickOffset',
    'tickOpacity',
    'tickRound',
    'tickSize',
    'tickWidth',
    'ticks',
    'title',
    'titleAlign',
    'titleAnchor',
    'titleAngle',
    'titleBaseline',
    'titleColor',
    'titleFont',
    'titleFontSize',
    'titleFontStyle',
    'titleFontWeight',
    'titleLimit',
    'titleLineHeight',
    'titleOpacity',
    'titlePadding',
    'titleX',
    'titleY',
    'translate',
    'values',
    'zindex',
])
const allowedConfigKeys = new Set([
    'arc',
    'area',
    'axis',
    'axisBand',
    'axisBottom',
    'axisDiscrete',
    'axisLeft',
    'axisPoint',
    'axisQuantitative',
    'axisRight',
    'axisTemporal',
    'axisTop',
    'axisX',
    'axisXBand',
    'axisXDiscrete',
    'axisXPoint',
    'axisXQuantitative',
    'axisXTemporal',
    'axisY',
    'axisYBand',
    'axisYDiscrete',
    'axisYPoint',
    'axisYQuantitative',
    'axisYTemporal',
    'background',
    'bar',
    'boxplot',
    'circle',
    'errorband',
    'errorbar',
    'font',
    'legend',
    'legendGradient',
    'legendSymbol',
    'line',
    'mark',
    'point',
    'range',
    'rect',
    'rule',
    'scale',
    'style',
    'text',
    'tick',
    'title',
    'trail',
    'view',
])
const allowedLegendKeys = new Set([
    'aria',
    'clipHeight',
    'columns',
    'columnPadding',
    'cornerRadius',
    'direction',
    'fillColor',
    'format',
    'formatType',
    'gradientLength',
    'gradientOpacity',
    'gradientStrokeColor',
    'gradientStrokeWidth',
    'gradientThickness',
    'gridAlign',
    'labelAlign',
    'labelBaseline',
    'labelColor',
    'labelFont',
    'labelFontSize',
    'labelFontStyle',
    'labelFontWeight',
    'labelLimit',
    'labelOffset',
    'labelOpacity',
    'labelOverlap',
    'labelPadding',
    'labelSeparation',
    'legendX',
    'legendY',
    'offset',
    'orient',
    'padding',
    'rowPadding',
    'strokeColor',
    'symbolBaseFillColor',
    'symbolBaseStrokeColor',
    'symbolDash',
    'symbolDashOffset',
    'symbolDirection',
    'symbolFillColor',
    'symbolLimit',
    'symbolOffset',
    'symbolOpacity',
    'symbolSize',
    'symbolStrokeColor',
    'symbolStrokeWidth',
    'symbolType',
    'tickCount',
    'title',
    'titleAlign',
    'titleAnchor',
    'titleBaseline',
    'titleColor',
    'titleFont',
    'titleFontSize',
    'titleFontStyle',
    'titleFontWeight',
    'titleLimit',
    'titleLineHeight',
    'titleOpacity',
    'titleOrient',
    'titlePadding',
    'type',
    'values',
    'zindex',
])
const allowedHeaderKeys = new Set([
    'format',
    'formatType',
    'labelAlign',
    'labelAngle',
    'labelAnchor',
    'labelBaseline',
    'labelColor',
    'labelFont',
    'labelFontSize',
    'labelFontStyle',
    'labelFontWeight',
    'labelLimit',
    'labelLineHeight',
    'labelOrient',
    'labelPadding',
    'labels',
    'title',
    'titleAlign',
    'titleAnchor',
    'titleBaseline',
    'titleColor',
    'titleFont',
    'titleFontSize',
    'titleFontStyle',
    'titleFontWeight',
    'titleLimit',
    'titleLineHeight',
    'titleOrient',
    'titlePadding',
])
const allowedViewKeys = new Set([
    'clip',
    'continuousHeight',
    'continuousWidth',
    'cornerRadius',
    'discreteHeight',
    'discreteWidth',
    'fill',
    'fillOpacity',
    'opacity',
    'stroke',
    'strokeCap',
    'strokeDash',
    'strokeDashOffset',
    'strokeJoin',
    'strokeMiterLimit',
    'strokeOpacity',
    'strokeWidth',
    'step',
])
const allowedTitleConfigKeys = new Set([
    'anchor',
    'angle',
    'baseline',
    'color',
    'dx',
    'dy',
    'font',
    'fontSize',
    'fontStyle',
    'fontWeight',
    'frame',
    'limit',
    'lineHeight',
    'offset',
    'orient',
    'subtitleColor',
    'subtitleFont',
    'subtitleFontSize',
    'subtitleFontStyle',
    'subtitleFontWeight',
    'subtitleLineHeight',
    'subtitlePadding',
])
const allowedResolveKeys = new Set(['axis', 'legend', 'scale'])

const getMarkType = (mark: unknown): string | null => {
    if (typeof mark === 'string') {
        return mark
    }

    if (isPlainObject(mark) && typeof mark.type === 'string') {
        return mark.type
    }

    return null
}

const mergePadding = (padding: unknown, defaults: typeof DEFAULT_CHART_PADDING): typeof DEFAULT_CHART_PADDING => {
    if (typeof padding === 'number' && Number.isFinite(padding)) {
        return {
            top: Math.max(padding, defaults.top),
            right: Math.max(padding, defaults.right),
            bottom: Math.max(padding, defaults.bottom),
            left: Math.max(padding, defaults.left),
        }
    }

    if (isPlainObject(padding)) {
        return {
            top: Math.max(typeof padding.top === 'number' ? padding.top : 0, defaults.top),
            right: Math.max(typeof padding.right === 'number' ? padding.right : 0, defaults.right),
            bottom: Math.max(typeof padding.bottom === 'number' ? padding.bottom : 0, defaults.bottom),
            left: Math.max(typeof padding.left === 'number' ? padding.left : 0, defaults.left),
        }
    }

    return defaults
}

const clampArcRadius = (mark: PlainObject, key: string): void => {
    const value = mark[key]
    if (typeof value === 'number' && Number.isFinite(value) && value > MAX_ARC_RADIUS) {
        mark[key] = MAX_ARC_RADIUS
    }
}

const normalizeArcMark = (mark: unknown): void => {
    if (!isPlainObject(mark) || getMarkType(mark) !== 'arc') {
        return
    }

    clampArcRadius(mark, 'outerRadius')
    clampArcRadius(mark, 'radius')
    clampArcRadius(mark, 'radius2')

    if (typeof mark.innerRadius === 'number' && Number.isFinite(mark.innerRadius)) {
        mark.innerRadius = Math.min(mark.innerRadius, MAX_ARC_RADIUS - 16)
    }
}

const normalizeArcLegendChannel = (encoding: PlainObject, channel: string): void => {
    const channelEncoding = encoding[channel]
    if (!isPlainObject(channelEncoding) || channelEncoding.legend === null) {
        return
    }

    const existingLegend = isPlainObject(channelEncoding.legend) ? channelEncoding.legend : {}
    channelEncoding.legend = {
        ...existingLegend,
        orient: 'bottom',
        direction: 'horizontal',
        columns: typeof existingLegend.columns === 'number' ? existingLegend.columns : 3,
        labelLimit: typeof existingLegend.labelLimit === 'number' ? existingLegend.labelLimit : 180,
        titleLimit: typeof existingLegend.titleLimit === 'number' ? existingLegend.titleLimit : 180,
    }
}

const normalizeArcLegend = (encoding: unknown): void => {
    if (!isPlainObject(encoding)) {
        return
    }

    normalizeArcLegendChannel(encoding, 'color')
    normalizeArcLegendChannel(encoding, 'fill')
}

const normalizeLayout = (spec: PlainObject, path: string = 'spec'): boolean => {
    const isArcSpec = getMarkType(spec.mark) === 'arc'

    if (path === 'spec') {
        spec.padding = mergePadding(spec.padding, isArcSpec ? DEFAULT_ARC_CHART_PADDING : DEFAULT_CHART_PADDING)
    }

    if (isArcSpec) {
        normalizeArcMark(spec.mark)
        normalizeArcLegend(spec.encoding)
    }

    const childSpecs = [spec.layer, spec.hconcat, spec.vconcat, spec.concat]
    const hasArcChild = childSpecs.some((children) => {
        if (!Array.isArray(children)) {
            return false
        }
        return children.some((child) => isPlainObject(child) && normalizeLayout(child, `${path}.child`))
    })

    const hasArcNestedSpec = isPlainObject(spec.spec) ? normalizeLayout(spec.spec, `${path}.spec`) : false
    const containsArc = isArcSpec || hasArcChild || hasArcNestedSpec

    if (path === 'spec' && containsArc) {
        spec.padding = mergePadding(spec.padding, DEFAULT_ARC_CHART_PADDING)
    }

    return containsArc
}

const validateMark = (mark: unknown, warnings: string[], path: string = 'mark'): void => {
    if (typeof mark === 'string') {
        if (!allowedMarks.has(mark)) {
            throw new VegaLiteValidationError(`Unsupported mark "${mark}".`)
        }
        return
    }

    if (!isPlainObject(mark)) {
        throw new VegaLiteValidationError('Mark must be a string or object.')
    }

    removeUnsupportedKeys(mark, allowedMarkKeys, path, warnings)
    const type = mark.type
    if (typeof type !== 'string' || !allowedMarks.has(type)) {
        throw new VegaLiteValidationError('Object mark requires an allowed type.')
    }

    Object.entries(mark).forEach(([key, value]) => {
        if (key === 'type') {
            return
        }
        validateSimpleVegaValue(value, `${path}.${key}`)
    })
}

const validateMarkConfig = (mark: unknown, warnings: string[], path: string): void => {
    if (!isPlainObject(mark)) {
        throw new VegaLiteValidationError('Config mark must be an object.')
    }

    removeUnsupportedKeys(mark, allowedMarkKeys, path, warnings)
    Object.entries(mark).forEach(([key, value]) => {
        if (key === 'type') {
            if (typeof value !== 'string' || !allowedMarks.has(value)) {
                throw new VegaLiteValidationError('Config mark type must be an allowed mark.')
            }
            return
        }
        validateSimpleVegaValue(value, `${path}.${key}`)
    })
}

const validateScale = (scale: unknown, path: string, warnings: string[]): void => {
    if (scale === null || scale === undefined) {
        return
    }

    if (!isPlainObject(scale)) {
        throw new VegaLiteValidationError(`Scale at ${path} must be an object.`)
    }

    removeUnsupportedKeys(scale, allowedScaleKeys, path, warnings)
    Object.entries(scale).forEach(([key, value]) => validateSimpleVegaValue(value, `${path}.${key}`))
}

const validateAxis = (axis: unknown, path: string, warnings: string[]): void => {
    if (axis === null || axis === undefined) {
        return
    }

    if (!isPlainObject(axis)) {
        throw new VegaLiteValidationError(`Axis at ${path} must be an object.`)
    }

    removeUnsupportedKeys(axis, allowedAxisKeys, path, warnings)
    Object.entries(axis).forEach(([key, value]) => {
        if (key === 'labelExpr') {
            delete axis[key]
            warnings.push(`Removed unsupported expression key "${key}" at ${path}.`)
            return
        }

        if (key === 'title' || key === 'format' || key === 'orient') {
            if (typeof value !== 'string') {
                throw new VegaLiteValidationError(`Expected string at ${path}.${key}.`)
            }
            assertSafeString(value, `${path}.${key}`)
            return
        }
        assertPrimitiveOrPrimitiveArray(value, `${path}.${key}`)
    })
}

const validateLegend = (legend: unknown, path: string, warnings: string[]): void => {
    if (legend === null || legend === undefined) {
        return
    }

    if (!isPlainObject(legend)) {
        throw new VegaLiteValidationError(`Legend at ${path} must be an object.`)
    }

    removeUnsupportedKeys(legend, allowedLegendKeys, path, warnings)
    Object.entries(legend).forEach(([key, value]) => validateSimpleVegaValue(value, `${path}.${key}`))
}

const validateHeader = (header: unknown, path: string, warnings: string[]): void => {
    if (header === null || header === undefined) {
        return
    }

    if (!isPlainObject(header)) {
        throw new VegaLiteValidationError(`Header at ${path} must be an object.`)
    }

    removeUnsupportedKeys(header, allowedHeaderKeys, path, warnings)
    Object.entries(header).forEach(([key, value]) => validateSimpleVegaValue(value, `${path}.${key}`))
}

const validateFieldCompatibility = (
    fieldName: string,
    encodingType: unknown,
    fieldsByName: Map<string, SQLVisualizationGenerationField>,
    path: string
): void => {
    const field = fieldsByName.get(fieldName)
    if (!field) {
        throw new VegaLiteValidationError(`Unknown field "${fieldName}" at ${path}.`)
    }

    if (encodingType === undefined) {
        return
    }

    if (typeof encodingType !== 'string' || !allowedEncodingTypes.has(encodingType)) {
        throw new VegaLiteValidationError(`Unsupported encoding type at ${path}.type.`)
    }

    if (field.semanticType === 'quantitative' && encodingType === 'temporal') {
        throw new VegaLiteValidationError(`Field "${fieldName}" is not temporal.`)
    }

    if (field.semanticType === 'temporal' && encodingType === 'quantitative') {
        throw new VegaLiteValidationError(`Field "${fieldName}" is not quantitative.`)
    }

    if (field.semanticType === 'nominal' && encodingType === 'quantitative') {
        throw new VegaLiteValidationError(`Field "${fieldName}" is not quantitative.`)
    }
}

const validateEncodingDefinition = (
    definition: unknown,
    fieldsByName: Map<string, SQLVisualizationGenerationField>,
    path: string,
    warnings: string[]
): void => {
    if (!isPlainObject(definition)) {
        throw new VegaLiteValidationError(`Encoding definition at ${path} must be an object.`)
    }

    removeUnsupportedKeys(definition, allowedEncodingKeys, path, warnings)

    const fieldName = definition.field
    if (fieldName !== undefined) {
        if (typeof fieldName !== 'string') {
            throw new VegaLiteValidationError(`Field at ${path}.field must be a string.`)
        }
        validateFieldCompatibility(fieldName, definition.type, fieldsByName, path)
    }

    if (definition.title !== undefined) {
        if (typeof definition.title !== 'string') {
            throw new VegaLiteValidationError(`Title at ${path}.title must be a string.`)
        }
        assertSafeString(definition.title, `${path}.title`)
    }

    if (definition.format !== undefined) {
        if (typeof definition.format !== 'string') {
            throw new VegaLiteValidationError(`Format at ${path}.format must be a string.`)
        }
        assertSafeString(definition.format, `${path}.format`, 64)
    }

    if (definition.sort !== undefined) {
        validateSimpleVegaValue(definition.sort, `${path}.sort`)
    }

    if (definition.aggregate !== undefined) {
        assertPrimitiveOrPrimitiveArray(definition.aggregate, `${path}.aggregate`)
    }

    if (definition.bin !== undefined) {
        validateSimpleVegaValue(definition.bin, `${path}.bin`)
    }

    if (definition.timeUnit !== undefined) {
        assertPrimitiveOrPrimitiveArray(definition.timeUnit, `${path}.timeUnit`)
    }

    if (definition.stack !== undefined) {
        assertPrimitiveOrPrimitiveArray(definition.stack, `${path}.stack`)
    }

    if (definition.value !== undefined) {
        assertPrimitiveOrPrimitiveArray(definition.value, `${path}.value`)
    }

    if (definition.datum !== undefined) {
        assertPrimitiveOrPrimitiveArray(definition.datum, `${path}.datum`)
    }

    if (definition.impute !== undefined) {
        validateSimpleVegaValue(definition.impute, `${path}.impute`)
    }

    validateScale(definition.scale, `${path}.scale`, warnings)
    validateAxis(definition.axis, `${path}.axis`, warnings)
    validateLegend(definition.legend, `${path}.legend`, warnings)
    validateHeader(definition.header, `${path}.header`, warnings)
}

const validateEncoding = (encoding: unknown, fields: SQLVisualizationGenerationField[], warnings: string[]): void => {
    if (!isPlainObject(encoding)) {
        throw new VegaLiteValidationError('Encoding must be an object.')
    }

    removeUnsupportedKeys(encoding, allowedEncodingChannels, 'encoding', warnings)

    const fieldsByName = new Map(fields.map((field) => [field.field, field]))
    Object.entries(encoding).forEach(([channel, definition]) => {
        if (channel === 'tooltip' && definition === true) {
            return
        }

        if (channel === 'tooltip' && Array.isArray(definition)) {
            definition.forEach((item, index) =>
                validateEncodingDefinition(item, fieldsByName, `encoding.tooltip[${index}]`, warnings)
            )
            return
        }

        if ((channel === 'detail' || channel === 'order') && Array.isArray(definition)) {
            definition.forEach((item, index) =>
                validateEncodingDefinition(item, fieldsByName, `encoding.${channel}[${index}]`, warnings)
            )
            return
        }

        validateEncodingDefinition(definition, fieldsByName, `encoding.${channel}`, warnings)
    })
}

const validateConfig = (config: unknown, warnings: string[]): void => {
    if (config === undefined) {
        return
    }

    if (!isPlainObject(config)) {
        throw new VegaLiteValidationError('Config must be an object.')
    }

    removeUnsupportedKeys(config, allowedConfigKeys, 'config', warnings)

    Object.entries(config).forEach(([key, value]) => {
        if (value === null) {
            delete config[key]
            warnings.push(`Removed null config block "${key}".`)
            return
        }

        if (key.startsWith('axis')) {
            validateAxis(value, `config.${key}`, warnings)
            return
        }

        if (key === 'legend' || key === 'legendGradient' || key === 'legendSymbol') {
            validateLegend(value, `config.${key}`, warnings)
            return
        }

        if (key === 'view') {
            if (!isPlainObject(value)) {
                throw new VegaLiteValidationError('Config view must be an object.')
            }
            removeUnsupportedKeys(value, allowedViewKeys, 'config.view', warnings)
            Object.entries(value).forEach(([nestedKey, nestedValue]) =>
                assertPrimitiveOrPrimitiveArray(nestedValue, `config.view.${nestedKey}`)
            )
            return
        }

        if (key === 'mark') {
            validateMarkConfig(value, warnings, 'config.mark')
            return
        }

        if (allowedMarks.has(key)) {
            validateMarkConfig(value, warnings, `config.${key}`)
            return
        }

        if (key === 'title') {
            if (!isPlainObject(value)) {
                throw new VegaLiteValidationError('Config title must be an object.')
            }
            removeUnsupportedKeys(value, allowedTitleConfigKeys, 'config.title', warnings)
            Object.entries(value).forEach(([nestedKey, nestedValue]) =>
                assertPrimitiveOrPrimitiveArray(nestedValue, `config.title.${nestedKey}`)
            )
            return
        }

        validateSimpleVegaValue(value, `config.${key}`)
    })
}

const validateData = (data: unknown, path: string): void => {
    if (!isPlainObject(data)) {
        throw new VegaLiteValidationError(`Spec at ${path} must include data: { name: "posthog_results" }.`)
    }

    Object.keys(data).forEach((key) => {
        if (key !== 'name') {
            throw new VegaLiteValidationError(`Unsupported key "${key}" at ${path}.`)
        }
    })
    if (data.name !== POSTHOG_RESULTS_DATASET) {
        throw new VegaLiteValidationError('Spec data source must be named "posthog_results".')
    }
}

const validateResolve = (resolve: unknown, warnings: string[]): void => {
    if (resolve === undefined) {
        return
    }

    if (!isPlainObject(resolve)) {
        throw new VegaLiteValidationError('Resolve must be an object.')
    }

    removeUnsupportedKeys(resolve, allowedResolveKeys, 'resolve', warnings)
    Object.entries(resolve).forEach(([key, value]) => validateSimpleVegaValue(value, `resolve.${key}`))
}

const validateFacet = (facet: unknown, fields: SQLVisualizationGenerationField[], warnings: string[]): void => {
    if (facet === undefined) {
        return
    }

    if (!isPlainObject(facet)) {
        throw new VegaLiteValidationError('Facet must be an object.')
    }

    const facetFieldsByName = new Map(fields.map((field) => [field.field, field]))
    removeUnsupportedKeys(
        facet,
        new Set(['row', 'column', 'field', 'type', 'title', 'header', 'sort']),
        'facet',
        warnings
    )
    Object.entries(facet).forEach(([key, value]) => {
        if (key === 'row' || key === 'column') {
            validateEncodingDefinition(value, facetFieldsByName, `facet.${key}`, warnings)
            return
        }

        if (key === 'field') {
            if (typeof value !== 'string') {
                throw new VegaLiteValidationError('Facet field must be a string.')
            }
            validateFieldCompatibility(value, facet.type, facetFieldsByName, 'facet')
            return
        }

        if (key === 'header') {
            validateHeader(value, 'facet.header', warnings)
            return
        }

        validateSimpleVegaValue(value, `facet.${key}`)
    })
}

const validateSpecBody = (
    spec: PlainObject,
    fields: SQLVisualizationGenerationField[],
    warnings: string[],
    path: string,
    requiresData: boolean
): void => {
    removeUnsupportedKeys(spec, allowedTopLevelKeys, path, warnings)

    if (spec.$schema !== undefined) {
        if (typeof spec.$schema !== 'string' || !SUPPORTED_VEGA_LITE_SCHEMAS.has(spec.$schema)) {
            throw new VegaLiteValidationError('Only Vega-Lite v5 or v6 schemas are supported.')
        }
    } else if (path === 'spec') {
        spec.$schema = VEGA_LITE_SCHEMA
    }

    if (spec.title !== undefined) {
        if (typeof spec.title !== 'string' && !isPlainObject(spec.title)) {
            throw new VegaLiteValidationError(`Spec title at ${path}.title must be a string or object.`)
        }
        validateSimpleVegaValue(spec.title, `${path}.title`)
    }

    if (spec.description !== undefined) {
        if (typeof spec.description !== 'string') {
            throw new VegaLiteValidationError(`Spec description at ${path}.description must be a string.`)
        }
        assertSafeString(spec.description, `${path}.description`, MAX_DESCRIPTION_LENGTH)
    }

    if (spec.width !== undefined) {
        validateDimension(spec.width, `${path}.width`)
    } else if (path === 'spec') {
        spec.width = 'container'
    }

    if (spec.height !== undefined) {
        validateDimension(spec.height, `${path}.height`)
    } else if (path === 'spec') {
        spec.height = 320
    }

    if (spec.data !== undefined) {
        validateData(spec.data, `${path}.data`)
    } else if (requiresData) {
        spec.data = { name: POSTHOG_RESULTS_DATASET }
    }

    if (spec.mark !== undefined) {
        validateMark(spec.mark, warnings, `${path}.mark`)
    }

    if (spec.encoding !== undefined) {
        validateEncoding(spec.encoding, fields, warnings)
    }

    validateConfig(spec.config, warnings)
    validateResolve(spec.resolve, warnings)
    validateFacet(spec.facet, fields, warnings)

    if (spec.layer !== undefined) {
        validateSpecArray(spec.layer, fields, warnings, `${path}.layer`)
    }
    if (spec.hconcat !== undefined) {
        validateSpecArray(spec.hconcat, fields, warnings, `${path}.hconcat`)
    }
    if (spec.vconcat !== undefined) {
        validateSpecArray(spec.vconcat, fields, warnings, `${path}.vconcat`)
    }
    if (spec.concat !== undefined) {
        validateSpecArray(spec.concat, fields, warnings, `${path}.concat`)
    }
    if (spec.spec !== undefined) {
        if (!isPlainObject(spec.spec)) {
            throw new VegaLiteValidationError(`Nested spec at ${path}.spec must be an object.`)
        }
        validateSpecBody(spec.spec, fields, warnings, `${path}.spec`, false)
    }

    ;['columns', 'spacing', 'bounds', 'center', 'align', 'autosize', 'background', 'padding'].forEach((key) => {
        if (spec[key] !== undefined) {
            validateSimpleVegaValue(spec[key], `${path}.${key}`)
        }
    })

    const hasUnitSpec = spec.mark !== undefined && spec.encoding !== undefined
    const hasComposition =
        spec.layer !== undefined ||
        spec.hconcat !== undefined ||
        spec.vconcat !== undefined ||
        spec.concat !== undefined ||
        spec.spec !== undefined
    if (!hasUnitSpec && !hasComposition) {
        throw new VegaLiteValidationError(`Spec at ${path} must include a mark with encoding or a composition.`)
    }
}

const validateSpecArray = (
    specs: unknown,
    fields: SQLVisualizationGenerationField[],
    warnings: string[],
    path: string
): void => {
    if (!Array.isArray(specs)) {
        throw new VegaLiteValidationError(`Spec array at ${path} must be an array.`)
    }
    if (specs.length === 0 || specs.length > 20) {
        throw new VegaLiteValidationError(`Spec array at ${path} must contain between 1 and 20 specs.`)
    }

    specs.forEach((childSpec, index) => {
        if (!isPlainObject(childSpec)) {
            throw new VegaLiteValidationError(`Spec at ${path}[${index}] must be an object.`)
        }
        validateSpecBody(childSpec, fields, warnings, `${path}[${index}]`, false)
    })
}

export const validateVegaLiteSpec = (
    spec: unknown,
    fields: SQLVisualizationGenerationField[]
): VegaLiteValidationResult => {
    const specJson = JSON.stringify(spec)
    if (!specJson) {
        throw new VegaLiteValidationError('Vega-Lite spec must be a JSON object.')
    }

    if (specJson.length > MAX_SPEC_JSON_LENGTH) {
        throw new VegaLiteValidationError('Vega-Lite spec is too large.')
    }

    if (!isPlainObject(spec)) {
        throw new VegaLiteValidationError('Vega-Lite spec must be a JSON object.')
    }

    const normalizedSpec = JSON.parse(specJson) as PlainObject
    const warnings: string[] = []
    validateSpecBody(normalizedSpec, fields, warnings, 'spec', true)
    normalizeLayout(normalizedSpec)

    return { spec: normalizedSpec, warnings }
}

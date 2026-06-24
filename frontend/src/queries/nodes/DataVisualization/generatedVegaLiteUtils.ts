import type {
    GeneratedVegaLiteChartSettings,
    GeneratedVegaLiteField,
    HogQLQueryResponse,
} from '~/queries/schema/schema-general'

export const DEFAULT_GENERATED_VEGA_LITE_PROMPT = 'Create the best chart suited for this data.'

export const GENERATED_VEGA_LITE_SYSTEM_PROMPT = [
    'Create a clean Vega or Vega-Lite visualization for this SQL result.',
    'Use the named posthog_results data source for the SQL result rows.',
    'You may use full Vega or Vega-Lite features, including transforms, params, selections, projections, datasets, inline values, expressions, and data URLs when they make the chart clearer.',
    'Prefer readable charts, but use richer Vega or Vega-Lite features when they make the data clearer.',
    'Return only Vega or Vega-Lite JSON.',
].join(' ')

const MAX_SAMPLE_ROWS = 20
const MAX_SAMPLE_VALUES_PER_COLUMN = 10
const MAX_STRING_LENGTH = 200
const MAX_JSON_VALUE_LENGTH = 400
const MAX_SPEC_JSON_LENGTH = 250000
const MIN_VIEW_DIMENSION = 120
const MAX_VIEW_DIMENSION = 2000
const VEGA_LITE_SCHEMA = 'https://vega.github.io/schema/vega-lite/v6.json'
const VEGA_SCHEMA = 'https://vega.github.io/schema/vega/v6.json'
const SUPPORTED_VEGA_SCHEMAS = new Set([
    VEGA_LITE_SCHEMA,
    'https://vega.github.io/schema/vega-lite/v5.json',
    VEGA_SCHEMA,
    'https://vega.github.io/schema/vega/v5.json',
])
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

const isSupportedVegaSchema = (schema: unknown): schema is string =>
    typeof schema === 'string' && SUPPORTED_VEGA_SCHEMAS.has(schema)

const isRawVegaSpec = (spec: PlainObject): boolean => {
    if (typeof spec.$schema === 'string') {
        return spec.$schema.includes('/schema/vega/')
    }

    return ['marks', 'signals', 'scales', 'axes', 'legends'].some((key) => Array.isArray(spec[key]))
}

const normalizeGeneratedVegaSpec = (spec: PlainObject): void => {
    const rawVegaSpec = isRawVegaSpec(spec)

    if (spec.$schema === undefined) {
        spec.$schema = rawVegaSpec ? VEGA_SCHEMA : VEGA_LITE_SCHEMA
    } else if (!isSupportedVegaSchema(spec.$schema)) {
        throw new VegaLiteValidationError('Only Vega and Vega-Lite v5 or v6 schemas are supported.')
    }

    if (spec.data === undefined) {
        spec.data = rawVegaSpec ? [{ name: POSTHOG_RESULTS_DATASET }] : { name: POSTHOG_RESULTS_DATASET }
    }
}

export const validateVegaLiteSpec = (
    spec: unknown,
    _fields: SQLVisualizationGenerationField[]
): VegaLiteValidationResult => {
    let specJson: string
    try {
        specJson = JSON.stringify(spec)
    } catch {
        throw new VegaLiteValidationError('Vega spec must be JSON-serializable.')
    }

    if (!specJson) {
        throw new VegaLiteValidationError('Vega spec must be a JSON object.')
    }

    if (specJson.length > MAX_SPEC_JSON_LENGTH) {
        throw new VegaLiteValidationError('Vega spec is too large.')
    }

    if (!isPlainObject(spec)) {
        throw new VegaLiteValidationError('Vega spec must be a JSON object.')
    }

    const normalizedSpec = JSON.parse(specJson) as PlainObject
    const warnings: string[] = []
    normalizeGeneratedVegaSpec(normalizedSpec)

    return { spec: normalizedSpec, warnings }
}

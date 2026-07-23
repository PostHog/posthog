import { InsightBuilderDimension, InsightBuilderMeasure } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

export type BuilderWell = 'rows' | 'columns' | 'values' | 'filters'

/** The wells that participate in chart capability checks — filters apply to every chart equally. */
export type CapabilityWell = 'rows' | 'columns' | 'values'

export interface BuilderWells {
    rows: InsightBuilderDimension[]
    columns: InsightBuilderDimension[]
    values: InsightBuilderMeasure[]
}

export interface WellRequirement {
    min: number
    /** null = unlimited */
    max: number | null
}

export interface ChartCapability {
    display: ChartDisplayType
    label: string
    rows: WellRequirement
    columns: WellRequirement
    values: WellRequirement
    /** When the Columns well is filled, cap Values at this many (series splitting replaces the series list) */
    maxValuesWithColumns?: number
    /** Requires at least one field across all wells */
    requiresAnyField?: boolean
    /** Shown in the chart picker and preview empty states */
    requirementHint: string
    tip?: string
}

const CHART_SERIES_WELLS: Pick<ChartCapability, 'rows' | 'columns' | 'values' | 'maxValuesWithColumns'> = {
    rows: { min: 1, max: 1 },
    columns: { min: 0, max: 1 },
    values: { min: 1, max: null },
    maxValuesWithColumns: 1,
}

export const CHART_CAPABILITIES: ChartCapability[] = [
    {
        display: ChartDisplayType.ActionsTable,
        label: 'Table',
        rows: { min: 0, max: null },
        columns: { min: 0, max: null },
        values: { min: 0, max: null },
        requiresAnyField: true,
        requirementHint: 'Works with any fields — shows the grouped results as a table',
    },
    {
        display: ChartDisplayType.BoldNumber,
        label: 'Big number',
        rows: { min: 0, max: 0 },
        columns: { min: 0, max: 0 },
        values: { min: 1, max: 1 },
        requirementHint: 'Needs exactly 1 Value, with no Rows or Columns',
    },
    {
        display: ChartDisplayType.ActionsLineGraph,
        label: 'Line chart',
        ...CHART_SERIES_WELLS,
        requirementHint: 'Needs 1 Row and at least 1 Value',
        tip: 'A date column in Rows works best',
    },
    {
        display: ChartDisplayType.ActionsBar,
        label: 'Bar chart',
        rows: { min: 1, max: 1 },
        columns: { min: 0, max: 0 },
        values: { min: 1, max: null },
        requirementHint: 'Needs 1 Row and at least 1 Value',
    },
    {
        display: ChartDisplayType.ActionsStackedBar,
        label: 'Stacked bar chart',
        rows: { min: 1, max: 1 },
        columns: { min: 1, max: 1 },
        values: { min: 1, max: 1 },
        requirementHint: 'Needs 1 Row (stacked series), 1 Column (x-axis), and exactly 1 Value',
    },
    {
        display: ChartDisplayType.ActionsAreaGraph,
        label: 'Area chart',
        ...CHART_SERIES_WELLS,
        requirementHint: 'Needs 1 Row and at least 1 Value',
        tip: 'A date column in Rows works best',
    },
    {
        display: ChartDisplayType.ActionsPie,
        label: 'Pie chart',
        rows: { min: 1, max: 1 },
        columns: { min: 0, max: 0 },
        values: { min: 1, max: 1 },
        requirementHint: 'Needs 1 Row and exactly 1 Value',
    },
    {
        display: ChartDisplayType.TwoDimensionalHeatmap,
        label: 'Heatmap',
        rows: { min: 1, max: 1 },
        columns: { min: 1, max: 1 },
        values: { min: 1, max: 1 },
        requirementHint: 'Needs 1 Row, 1 Column, and exactly 1 Value',
    },
]

const WELL_LABELS: Record<CapabilityWell, string> = {
    rows: 'Rows',
    columns: 'Columns',
    values: 'Values',
}

export function getChartCapability(display: ChartDisplayType): ChartCapability | undefined {
    return CHART_CAPABILITIES.find((capability) => capability.display === display)
}

function missingWellProblem(well: CapabilityWell, count: number, requirement: WellRequirement): string | null {
    const label = WELL_LABELS[well]
    if (count < requirement.min) {
        return requirement.min === 1 ? `Add a field to ${label}` : `Add at least ${requirement.min} fields to ${label}`
    }
    return null
}

/**
 * User-facing problems that stop the chart from rendering; [] = renderable. Only *missing required*
 * fields count — extra fields in wells the chart doesn't use are silently ignored (see
 * effectiveWells), never flagged as an error.
 */
export function validateWellsForDisplay(wells: BuilderWells, display: ChartDisplayType): string[] {
    const capability = getChartCapability(display)
    if (!capability) {
        return [`This chart type isn't supported in the builder`]
    }

    const problems = [
        missingWellProblem('rows', wells.rows.length, capability.rows),
        missingWellProblem('columns', wells.columns.length, capability.columns),
        missingWellProblem('values', wells.values.length, capability.values),
    ].filter((problem): problem is string => problem !== null)

    if (capability.requiresAnyField && wells.rows.length + wells.columns.length + wells.values.length === 0) {
        problems.push('Add at least one field')
    }

    return problems
}

/**
 * The wells actually used to compile/render for a given chart, dropping fields the chart can't
 * express: wells it doesn't use (max 0) become empty, over-max wells are truncated, and Values is
 * capped once Columns is filled. The full wells stay in state so switching charts restores them.
 */
export function effectiveWells(wells: BuilderWells, display: ChartDisplayType): BuilderWells {
    const capability = getChartCapability(display)
    if (!capability) {
        return wells
    }
    const truncate = <T>(items: T[], requirement: WellRequirement): T[] =>
        requirement.max === null ? items : items.slice(0, Math.max(requirement.max, 0))

    const columns = truncate(wells.columns, capability.columns)
    let values = truncate(wells.values, capability.values)
    if (capability.maxValuesWithColumns !== undefined && columns.length > 0) {
        values = values.slice(0, capability.maxValuesWithColumns)
    }
    return { rows: truncate(wells.rows, capability.rows), columns, values }
}

/**
 * Whether a well accepts fields for the given chart type. Chart type is primary: a well the chart
 * doesn't use (max === 0) is disabled in the UI. Filters apply to every chart, so always enabled.
 */
export function isWellEnabled(well: BuilderWell, display: ChartDisplayType): boolean {
    if (well === 'filters') {
        return true
    }
    const capability = getChartCapability(display)
    if (!capability) {
        return true
    }
    return capability[well].max !== 0
}

/** Pick a sensible chart type for the current wells (used when the user hasn't chosen one explicitly). */
export function bestDisplayForWells(wells: BuilderWells, options?: { firstRowIsDate?: boolean }): ChartDisplayType {
    const { rows, columns, values } = wells

    if (values.length >= 1 && rows.length === 0 && columns.length === 0) {
        return values.length === 1 ? ChartDisplayType.BoldNumber : ChartDisplayType.ActionsTable
    }
    if (rows.length === 1 && values.length >= 1) {
        // A single-value column split reads as a stacked bar; anything wider falls back to the table
        if (columns.length === 1 && values.length === 1) {
            return ChartDisplayType.ActionsStackedBar
        }
        if (columns.length === 0) {
            return options?.firstRowIsDate ? ChartDisplayType.ActionsLineGraph : ChartDisplayType.ActionsBar
        }
    }
    // Shapes a single chart can't express (many row dims, wide column splits) show as a grouped table
    return ChartDisplayType.ActionsTable
}

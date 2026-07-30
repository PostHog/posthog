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
    // Convention across all charts: Columns is the primary axis (x-axis for cartesian charts,
    // the slices for pie, the grouping dimension for a table); Rows is the secondary breakdown
    // (the series split — multiple lines, stacked segments). Heatmap uses Columns=x, Rows=y.
    rows: WellRequirement
    columns: WellRequirement
    values: WellRequirement
    /** When a breakdown (Rows) is present, cap Values at this many — a breakdown already splits the series */
    maxValuesWithBreakdown?: number
    /** Requires at least one field across all wells */
    requiresAnyField?: boolean
    /** Shown in the chart picker and preview empty states */
    requirementHint: string
    tip?: string
    /**
     * What each well is called for this chart. Charts speak the user's language — X-axis /
     * Breakdown / Slices — instead of pivot-table Rows/Columns; the table and heatmap keep the
     * literal names. Missing entries fall back to the generic Rows/Columns/Values.
     */
    wellLabels?: Partial<Record<CapabilityWell, string>>
}

// Line and area share a shape: one x-axis Column, an optional Rows breakdown, one-or-more Values
const LINE_AREA_WELLS: Pick<ChartCapability, 'rows' | 'columns' | 'values' | 'maxValuesWithBreakdown' | 'wellLabels'> =
    {
        columns: { min: 1, max: 1 },
        rows: { min: 0, max: 1 },
        values: { min: 1, max: null },
        maxValuesWithBreakdown: 1,
        wellLabels: { columns: 'X-axis', rows: 'Breakdown' },
    }

export const CHART_CAPABILITIES: ChartCapability[] = [
    {
        display: ChartDisplayType.ActionsTable,
        label: 'Table',
        // Only Columns (dimensions) + Values (metrics) for now — Rows would imply a pivot, which isn't supported yet
        rows: { min: 0, max: 0 },
        columns: { min: 0, max: null },
        values: { min: 0, max: null },
        requiresAnyField: true,
        requirementHint: 'Add dimensions to Columns and metrics to Values',
    },
    {
        display: ChartDisplayType.BoldNumber,
        label: 'Big number',
        rows: { min: 0, max: 0 },
        columns: { min: 0, max: 0 },
        values: { min: 1, max: 1 },
        requirementHint: 'Needs exactly 1 Value',
        wellLabels: { values: 'Value' },
    },
    {
        display: ChartDisplayType.ActionsLineGraph,
        label: 'Line chart',
        ...LINE_AREA_WELLS,
        requirementHint: 'Needs an X-axis field and at least 1 Value',
        tip: 'Add a Breakdown to split the line into multiple series; a date column on the x-axis works best',
    },
    {
        display: ChartDisplayType.ActionsBar,
        label: 'Bar chart',
        columns: { min: 1, max: 1 },
        rows: { min: 0, max: 0 },
        values: { min: 1, max: null },
        requirementHint: 'Needs an X-axis field and at least 1 Value',
        wellLabels: { columns: 'X-axis', rows: 'Breakdown' },
    },
    {
        display: ChartDisplayType.ActionsStackedBar,
        label: 'Stacked bar chart',
        columns: { min: 1, max: 1 },
        rows: { min: 1, max: 1 },
        values: { min: 1, max: 1 },
        requirementHint: 'Needs an X-axis field, a Breakdown, and exactly 1 Value',
        wellLabels: { columns: 'X-axis', rows: 'Breakdown', values: 'Value' },
    },
    {
        display: ChartDisplayType.ActionsAreaGraph,
        label: 'Area chart',
        ...LINE_AREA_WELLS,
        requirementHint: 'Needs an X-axis field and at least 1 Value',
        tip: 'Add a Breakdown to split the area into multiple series; a date column on the x-axis works best',
    },
    {
        display: ChartDisplayType.ActionsPie,
        label: 'Pie chart',
        columns: { min: 1, max: 1 },
        rows: { min: 0, max: 0 },
        values: { min: 1, max: 1 },
        requirementHint: 'Needs a Slices field and exactly 1 Value',
        wellLabels: { columns: 'Slices', rows: 'Breakdown', values: 'Value' },
    },
    {
        display: ChartDisplayType.TwoDimensionalHeatmap,
        label: 'Heatmap',
        columns: { min: 1, max: 1 },
        rows: { min: 1, max: 1 },
        values: { min: 1, max: 1 },
        requirementHint: 'Needs 1 Column (x-axis), 1 Row (y-axis), and exactly 1 Value',
        wellLabels: { values: 'Value' },
    },
]

const WELL_LABELS: Record<CapabilityWell, string> = {
    rows: 'Rows',
    columns: 'Columns',
    values: 'Values',
}

/** What a well is called for the given chart type (e.g. Columns → "X-axis" on a bar chart). */
export function wellLabel(well: BuilderWell, display: ChartDisplayType): string {
    if (well === 'filters') {
        return 'Filters'
    }
    return getChartCapability(display)?.wellLabels?.[well] ?? WELL_LABELS[well]
}

export function getChartCapability(display: ChartDisplayType): ChartCapability | undefined {
    return CHART_CAPABILITIES.find((capability) => capability.display === display)
}

function missingWellProblem(label: string, count: number, requirement: WellRequirement): string | null {
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
        missingWellProblem(wellLabel('rows', display), wells.rows.length, capability.rows),
        missingWellProblem(wellLabel('columns', display), wells.columns.length, capability.columns),
        missingWellProblem(wellLabel('values', display), wells.values.length, capability.values),
    ].filter((problem): problem is string => problem !== null)

    if (capability.requiresAnyField && wells.rows.length + wells.columns.length + wells.values.length === 0) {
        problems.push('Add at least one field')
    }

    return problems
}

/**
 * The wells actually used to compile/render for a given chart, dropping fields the chart can't
 * express: wells it doesn't use (max 0) become empty, over-max wells are truncated, and Values is
 * capped once a breakdown (Rows) is present. The full wells stay in state so switching charts
 * restores them.
 */
export function effectiveWells(wells: BuilderWells, display: ChartDisplayType): BuilderWells {
    const capability = getChartCapability(display)
    if (!capability) {
        return wells
    }
    const truncate = <T>(items: T[], requirement: WellRequirement): T[] =>
        requirement.max === null ? items : items.slice(0, Math.max(requirement.max, 0))

    const rows = truncate(wells.rows, capability.rows)
    let values = truncate(wells.values, capability.values)
    if (capability.maxValuesWithBreakdown !== undefined && rows.length > 0) {
        values = values.slice(0, capability.maxValuesWithBreakdown)
    }
    return { rows, columns: truncate(wells.columns, capability.columns), values }
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

/** Why a field can't be added to this well for the current chart, or null if it can. */
export function addToWellDisabledReason(well: BuilderWell, display: ChartDisplayType): string | null {
    if (well === 'filters' || isWellEnabled(well, display)) {
        return null
    }
    const capability = getChartCapability(display)
    return `${capability?.label ?? 'This chart'} doesn't use ${wellLabel(well, display)}`
}

/**
 * Where a clicked field should land for the current chart: measures go to Values; dimensions go
 * to the first enabled dimension well with room (Columns is the primary axis), falling back to
 * the first enabled dimension well (replace-on-full applies, matching drag), then Values
 * (e.g. Big number, where a clicked dimension becomes a count-distinct measure).
 */
export function bestWellForField(
    field: { isNumerical: boolean },
    wells: BuilderWells,
    display: ChartDisplayType
): CapabilityWell {
    if (field.isNumerical) {
        return 'values'
    }
    const capability = getChartCapability(display)
    const enabledDimensionWells = (['columns', 'rows'] as const).filter((well) => isWellEnabled(well, display))
    const withRoom = enabledDimensionWells.find((well) => {
        const max = capability?.[well].max
        return max === undefined || max === null || wells[well].length < max
    })
    return withRoom ?? enabledDimensionWells[0] ?? 'values'
}

/** Pick a sensible chart type for the current wells (used when the user hasn't chosen one explicitly). */
export function bestDisplayForWells(wells: BuilderWells, options?: { firstColumnIsDate?: boolean }): ChartDisplayType {
    const { rows, columns, values } = wells

    if (values.length >= 1 && rows.length === 0 && columns.length === 0) {
        return values.length === 1 ? ChartDisplayType.BoldNumber : ChartDisplayType.ActionsTable
    }
    if (columns.length === 1 && values.length >= 1) {
        // A single Column x-axis with a single Row breakdown reads as a stacked bar
        if (rows.length === 1 && values.length === 1) {
            return ChartDisplayType.ActionsStackedBar
        }
        if (rows.length === 0) {
            return options?.firstColumnIsDate ? ChartDisplayType.ActionsLineGraph : ChartDisplayType.ActionsBar
        }
    }
    // Shapes no single chart can express (Rows without a Column x-axis, wide splits) show as a table
    return ChartDisplayType.ActionsTable
}

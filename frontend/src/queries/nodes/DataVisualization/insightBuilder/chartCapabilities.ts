import { InsightBuilderDimension, InsightBuilderMeasure } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

export type BuilderWell = 'rows' | 'columns' | 'values'

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
        display: ChartDisplayType.PivotTable,
        label: 'Pivot table',
        rows: { min: 1, max: null },
        columns: { min: 0, max: null },
        values: { min: 1, max: null },
        requirementHint: 'Needs at least 1 Row and 1 Value — Columns spread across the top',
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
        ...CHART_SERIES_WELLS,
        requirementHint: 'Needs 1 Row and at least 1 Value',
    },
    {
        display: ChartDisplayType.ActionsStackedBar,
        label: 'Stacked bar chart',
        ...CHART_SERIES_WELLS,
        requirementHint: 'Needs 1 Row and at least 1 Value',
        tip: 'Add a field to Columns to stack by its values',
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

const WELL_LABELS: Record<BuilderWell, string> = {
    rows: 'Rows',
    columns: 'Columns',
    values: 'Values',
}

export function getChartCapability(display: ChartDisplayType): ChartCapability | undefined {
    return CHART_CAPABILITIES.find((capability) => capability.display === display)
}

function wellProblems(well: BuilderWell, count: number, requirement: WellRequirement, chartLabel: string): string[] {
    const problems: string[] = []
    const label = WELL_LABELS[well]

    if (count < requirement.min) {
        problems.push(
            requirement.min === 1 ? `Add a field to ${label}` : `Add at least ${requirement.min} fields to ${label}`
        )
    }
    if (requirement.max !== null && count > requirement.max) {
        problems.push(
            requirement.max === 0
                ? `${chartLabel}s don't use ${label} — remove the field`
                : `${chartLabel}s support only ${requirement.max} field in ${label}`
        )
    }
    return problems
}

/** Returns user-facing problems preventing the wells from rendering as `display`; [] = valid. */
export function validateWellsForDisplay(wells: BuilderWells, display: ChartDisplayType): string[] {
    const capability = getChartCapability(display)
    if (!capability) {
        return [`This chart type isn't supported in the builder`]
    }

    const problems = [
        ...wellProblems('rows', wells.rows.length, capability.rows, capability.label),
        ...wellProblems('columns', wells.columns.length, capability.columns, capability.label),
        ...wellProblems('values', wells.values.length, capability.values, capability.label),
    ]

    if (
        capability.maxValuesWithColumns !== undefined &&
        wells.columns.length > 0 &&
        wells.values.length > capability.maxValuesWithColumns
    ) {
        problems.push(`Only ${capability.maxValuesWithColumns} Value works when Columns is filled`)
    }

    if (capability.requiresAnyField && wells.rows.length + wells.columns.length + wells.values.length === 0) {
        problems.push('Add at least one field')
    }

    return problems
}

export interface WellDropResult {
    /** 'add' appends, 'replace' swaps out the single occupant of a full one-slot well, 'deny' rejects */
    mode: 'add' | 'replace' | 'deny'
    reason?: string
}

export function canDropInWell(well: BuilderWell, wells: BuilderWells, display: ChartDisplayType): WellDropResult {
    const capability = getChartCapability(display)
    if (!capability) {
        return { mode: 'add' }
    }

    const requirement = capability[well]
    const count = wells[well].length

    if (requirement.max === 0) {
        return { mode: 'deny', reason: `${capability.label}s don't use ${WELL_LABELS[well]}` }
    }
    if (requirement.max !== null && count >= requirement.max) {
        return requirement.max === 1
            ? { mode: 'replace' }
            : {
                  mode: 'deny',
                  reason: `${capability.label}s support only ${requirement.max} fields in ${WELL_LABELS[well]}`,
              }
    }
    return { mode: 'add' }
}

/** Pick a sensible chart type for the current wells (used when the user hasn't chosen one explicitly). */
export function bestDisplayForWells(wells: BuilderWells, options?: { firstRowIsDate?: boolean }): ChartDisplayType {
    const { rows, columns, values } = wells

    if (values.length >= 1 && rows.length === 0 && columns.length === 0) {
        return ChartDisplayType.BoldNumber
    }
    // Shapes a single chart can't express: many row dims, or a column split across several values
    if (rows.length >= 2 && values.length >= 1) {
        return ChartDisplayType.PivotTable
    }
    if (rows.length === 1 && values.length >= 1) {
        if (columns.length > 0) {
            return values.length > 1 ? ChartDisplayType.PivotTable : ChartDisplayType.ActionsStackedBar
        }
        return options?.firstRowIsDate ? ChartDisplayType.ActionsLineGraph : ChartDisplayType.ActionsBar
    }
    return ChartDisplayType.ActionsTable
}

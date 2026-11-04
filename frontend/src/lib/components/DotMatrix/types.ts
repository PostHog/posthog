import type { ReactNode } from 'react'

export type DotMatrixField<D> = (keyof D & string) | ((datum: D) => string | number | null)

export interface DotMatrixFields<D> {
    row: DotMatrixField<D>
    column: DotMatrixField<D>
    series?: DotMatrixField<D>
    value: DotMatrixField<D>
}

export interface DotMatrixAxisItem {
    key: string
    label?: string
    group?: string
}

export interface DotMatrixColumn extends DotMatrixAxisItem {
    partial?: boolean
}

export interface DotMatrixSeries extends DotMatrixAxisItem {
    color?: string
}

export interface DotMatrixGroup {
    items?: string[]
    key: string
    label: string
    color?: string
}

export interface DotMatrixCountBin {
    min: number
    color: string
    ink?: string
    label?: string
}

export interface DotMatrixCell<D> {
    rowKey: string
    columnKey: string
    values: Record<string, number>
    data: D[]
}

export interface DotMatrixDataOptions<D extends Record<string, unknown>> {
    data: D[]
    fields: DotMatrixFields<D>
    rows?: DotMatrixAxisItem[]
    columns?: DotMatrixColumn[]
    series?: DotMatrixSeries[]
}

export interface DotMatrixData<D> {
    rows: DotMatrixAxisItem[]
    columns: DotMatrixColumn[]
    series: DotMatrixSeries[]
    cells: Map<string, Map<string, DotMatrixCell<D>>>
    getCell: (rowKey: string, columnKey: string) => DotMatrixCell<D>
}

export interface DotMatrixCountOptions<D> {
    countOf?: 'activeSeries' | 'value' | ((cell: DotMatrixCell<D>) => number)
    selectedSeries?: string[]
    aggregateSelection?: (cell: DotMatrixCell<D>, selected: string[]) => number
}

export interface DotMatrixProps<D extends Record<string, unknown>>
    extends DotMatrixDataOptions<D>, DotMatrixCountOptions<D> {
    groups?: DotMatrixGroup[]
    columnsPerGroup?: number
    firstUseSeries?: (cell: DotMatrixCell<D>) => string[]
    mode?: 'dots' | 'count'
    // Up to three distinct positive thresholds, displayed in ascending order.
    sizeThresholds?: number[]
    countScale?: DotMatrixCountBin[]
    onSelectedSeriesChange?: (keys: string[]) => void
    rowHeader?: { title: string; width?: number; render?: (row: DotMatrixAxisItem) => ReactNode }
    trailingColumns?: { key: string; title: string; width: number; render: (rowKey: string) => ReactNode }[]
    // onCellClick wraps the cell in a button, so custom content must be noninteractive in that case.
    renderCell?: (cell: DotMatrixCell<D>) => ReactNode
    renderTooltip?: (cell: DotMatrixCell<D>) => ReactNode
    onCellClick?: (cell: DotMatrixCell<D>) => void
    cellWidth?: number
    rowClassName?: (row: DotMatrixAxisItem) => string | null
    className?: string
    legend?: false | DotMatrixLegendLabels
    loading?: boolean
    emptyState?: ReactNode
    pageSize?: number
}

export interface DotMatrixLegendLabels {
    itemLabel?: string
    valueLabel?: string
    countLabel?: string
    selectionLabel?: (count: number, mode: 'dots' | 'count') => string
    hint?: string
    footer?: ReactNode
}

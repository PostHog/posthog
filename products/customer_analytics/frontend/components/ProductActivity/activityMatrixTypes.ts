import type { DotMatrixProps } from 'lib/components/DotMatrix/types'

export interface ActivityMatrixDatum extends Record<string, unknown> {
    row: string
    column: string
    series: string
    value: number
}

export type ActivityMatrixProps = Pick<
    DotMatrixProps<ActivityMatrixDatum>,
    | 'data'
    | 'fields'
    | 'rows'
    | 'columns'
    | 'series'
    | 'aggregateSelection'
    | 'countOf'
    | 'rowHeader'
    | 'legend'
    | 'sizeThresholds'
    | 'countScale'
    | 'groups'
    | 'columnsPerGroup'
>

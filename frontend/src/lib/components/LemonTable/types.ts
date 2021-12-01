import { HTMLProps } from 'react'

export interface PaginationBase {
    /** By default pagination is only shown when there are multiple pages, but will always shown if this is `false`. */
    hideOnSinglePage?: boolean
}

export interface PaginationAuto extends PaginationBase {
    controlled?: false
    /** Size of each page (except the last one which can be smaller)/ */
    pageSize: number
}

export interface PaginationManual extends PaginationBase {
    controlled: true
    /** Size of each page (except the last one which can be smaller)/ */
    pageSize?: number
    /** Page currently on display. */
    currentPage?: number
    /** Total entry count for determining current position using `currentPage`. If not set, position is not shown. */
    entryCount?: number
    /** Next page navigation handler. */
    onForward?: () => void
    /** Previous page navigation handler. */
    onBackward?: () => void
}

export interface TableCellRepresentation {
    children?: any
    props?: HTMLProps<HTMLTableCellElement>
}

export type TableCellRenderResult = TableCellRepresentation | JSX.Element | string | number | false | null | undefined

export interface LemonTableColumn<T extends Record<string, any>, D extends keyof T | undefined> {
    title?: string | React.ReactNode
    key?: string
    dataIndex?: D
    render?:
        | ((dataValue: D extends keyof T ? T[D] : undefined, record: T, recordIndex: number) => TableCellRenderResult)
        | ((dataValue: D extends keyof T ? T[D] : undefined, record: T) => TableCellRenderResult)
        | ((record: T) => TableCellRenderResult)
    /** Sorting function. Set to `true` if using manual pagination, in which case you'll also have to provide `sorting` on the table. */
    sorter?: ((a: T, b: T) => number) | true
    className?: string
    /** Column content alignment. Left by default. Set to right for numerical values (amounts, days ago etc.) */
    align?: 'left' | 'right' | 'center'
    /** TODO: Whether the column should be sticky when scrolling */
    sticky?: boolean
    /** Set width. */
    width?: string | number
}
export type LemonTableColumns<T extends Record<string, any>> = LemonTableColumn<T, keyof T | undefined>[]

export interface ExpandableConfig<T extends Record<string, any>> {
    expandedRowRender: (record: T, recordIndex: number) => any
    rowExpandable?: (record: T) => boolean
}

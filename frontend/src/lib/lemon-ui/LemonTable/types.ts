import { CSSProperties, HTMLProps, ReactNode } from 'react'

export interface TableCellRepresentation {
    children?: any
    props?: HTMLProps<HTMLTableCellElement>
}

export type TableCellRenderResult =
    | TableCellRepresentation
    | ReactNode
    | JSX.Element
    | string
    | number
    | false
    | null
    | undefined

export interface LemonTableColumn<T extends Record<string, any>, D extends keyof T | undefined> {
    title?: string | React.ReactNode
    /** Tooltip to display on title hover. An info icon ("i" in circle) is shown when a tooltip is available. */
    tooltip?: string
    key?: string
    /** If true, the column is not displayed. Optional, defaults to not hidden. */
    isHidden?: boolean
    dataIndex?: D
    render?: (
        dataValue: D extends keyof T ? T[D] : undefined,
        record: T,
        recordIndex: number,
        rowCount: number
    ) => TableCellRenderResult
    /** Sorting function. Set to `true` if using manual pagination, in which case you'll also have to provide `sorting` on the table. */
    sorter?: ((a: T, b: T) => number) | true
    /** Menu containing extra column options, accessible via a "More" button in the title of the column. */
    more?: JSX.Element
    className?: string | ((dataValue: D extends keyof T ? T[D] : undefined, record: T, recordIndex: number) => string)
    style?:
        | CSSProperties
        | undefined
        | ((
              dataValue: D extends keyof T ? T[D] : undefined,
              record: T,
              recordIndex: number
          ) => CSSProperties | undefined)
    /** Column content alignment. Left by default. Set to right for numerical values (amounts, days ago etc.) */
    align?: 'left' | 'right' | 'center'
    /** TODO: Whether the column should be sticky when scrolling */
    sticky?: boolean
    /** Set width. */
    width?: string | number
    /** Whether the column's contents should expand to the size of the column. */
    fullWidth?: boolean
}
export interface LemonTableColumnGroup<T extends Record<string, any>> {
    title?: string | React.ReactNode
    children: LemonTableColumn<T, keyof T | undefined>[]
}
export type LemonTableColumns<T extends Record<string, any>> =
    | LemonTableColumn<T, keyof T | undefined>[]
    | LemonTableColumnGroup<T>[]

export interface ExpandableConfig<T extends Record<string, any>> {
    /** Row expansion render function. */
    expandedRowRender: (record: T, recordIndex: number) => any
    /* className string, or function that generates one,
     * which is applied to the TR that contains the expanded row
     */
    expandedRowClassName?: string | ((record: T, rowIndex: number) => string | null)
    /**
     * Function determining whether the row should be expandable:
     * A positive value (like true or 1) means that the row is expandable.
     * A zero (like 0 or false) means that the row isn't expandable.
     * A negative value (like -1) means that the row isn't expandable and that also the expand button cell is skipped.
     */
    rowExpandable?: (record: T, recordIndex: number) => boolean | number
    /** Called when row is expanded */
    onRowExpand?: (record: T, recordIndex: number, event: React.MouseEvent<HTMLElement, MouseEvent>) => void
    /** Called when row is collapsed */
    onRowCollapse?: (record: T, recordIndex: number, event: React.MouseEvent<HTMLElement, MouseEvent>) => void
    /** Disable indentation */
    noIndent?: boolean
    /** Optionally hide the row expansion toggle */
    showRowExpansionToggle?: boolean
    /**
     * Callback that checks if a row expandable state should be overridden
     * A positive value (like true or 1) means that the row is expanded.
     * A zero (like 0 or false) means that the row is collapsed.
     * A negative value (like -1) means that the row is uncontrolled.
     */
    isRowExpanded?: (record: T, recordIndex: number) => boolean | number
}

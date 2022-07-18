import React, {
    HTMLProps,
    useRef,
    useState,
    useContext,
    useEffect,
    createContext,
    useReducer,
    HTMLAttributes,
} from 'react'
import { IconUnfoldLess, IconUnfoldMore } from '../icons'
import { LemonButton } from '../LemonButton'
import { ExpandableConfig, LemonTableColumnGroup, TableCellRepresentation } from './types'
import clsx from 'clsx'

type FixedLegendsContextType = {
    left: (index: number) => number
    setColumnWidth: React.Dispatch<{ index: number; width: number }>
}

export const FixedLegendsContext = createContext<FixedLegendsContextType>({
    left: () => 0,
    setColumnWidth: () => {},
})

function FixedLegendsContextProvider<T>({
    columnGroups,
    onChange,
    children,
}: {
    columnGroups: LemonTableColumnGroup<T>[]
    onChange?: (widths: Record<number, number>) => void
    children: React.ReactNode
}): JSX.Element {
    const fixedColumnsLength = columnGroups
        .flatMap((columnGroup) => columnGroup.children.map((column) => column))
        .filter((column) => column.isFixed).length

    const [widths, setColumnWidth] = useReducer(
        (state: Record<number, number>, column: { index: number; width: number }) => {
            return { ...state, [column.index]: column.width }
        },
        {}
    )

    useEffect(() => {
        if (onChange && fixedColumnsLength === Object.keys(widths).length) {
            onChange(widths)
        }
    }, [fixedColumnsLength, onChange, widths])

    const left = (columnIndex: number): number => {
        let result = 0
        for (const [index, width] of Object.entries(widths)) {
            if (parseInt(index) < columnIndex) {
                result += width
            }
        }
        return result
    }

    return (
        <FixedLegendsContext.Provider
            value={{
                left,
                setColumnWidth,
            }}
        >
            {children}
        </FixedLegendsContext.Provider>
    )
}

type FixableColumnProps = {
    index: number
} & HTMLAttributes<HTMLTableCellElement>

function FixedColumn({ index, children, ...props }: FixableColumnProps): JSX.Element {
    const ref = useRef<HTMLTableCellElement | null>(null)
    const { setColumnWidth } = useContext(FixedLegendsContext)

    useEffect(() => {
        if (ref.current) {
            const rect = ref.current.getBoundingClientRect()
            setColumnWidth({ index, width: rect.width })
        }
    }, [index, ref, setColumnWidth])

    return (
        <td ref={ref} {...props}>
            {children}
        </td>
    )
}

export interface TableRowProps<T extends Record<string, any>> {
    record: T
    recordIndex: number
    rowKeyDetermined: string | number
    rowClassNameDetermined: string | null | undefined
    rowRibbonColorDetermined: string | null | undefined
    rowStatusDetermined: 'highlighted' | null | undefined
    columnGroups: LemonTableColumnGroup<T>[]
    onRow: ((record: T) => Omit<HTMLProps<HTMLTableRowElement>, 'key'>) | undefined
    expandable: ExpandableConfig<T> | undefined
    isFixedRow?: boolean
    setFixedWidths?: (widths: Record<number, number>) => void
    fixedWidths?: Record<number, number>
    lastFixedIndex?: [number, number]
    isScrollable?: boolean
}

function TableRowRaw<T extends Record<string, any>>({
    record,
    recordIndex,
    rowKeyDetermined,
    rowClassNameDetermined,
    rowRibbonColorDetermined,
    rowStatusDetermined,
    columnGroups,
    onRow,
    expandable,
    isFixedRow,
    setFixedWidths,
    fixedWidths,
    lastFixedIndex,
    isScrollable,
}: TableRowProps<T>): JSX.Element {
    const [isRowExpandedLocal, setIsRowExpanded] = useState(false)
    const rowExpandable: number = Number(
        !!expandable && (!expandable.rowExpandable || expandable.rowExpandable(record))
    )
    const isRowExpanded =
        !expandable?.isRowExpanded || expandable?.isRowExpanded?.(record) === -1
            ? isRowExpandedLocal
            : !!expandable?.isRowExpanded?.(record)

    const row = (
        <>
            <tr
                data-row-key={rowKeyDetermined}
                {...onRow?.(record)}
                className={clsx(
                    rowClassNameDetermined,
                    rowStatusDetermined && `LemonTable__tr--status-${rowStatusDetermined}`
                )}
            >
                {rowRibbonColorDetermined !== undefined && (
                    <td
                        className="LemonTable__ribbon"
                        style={{ backgroundColor: rowRibbonColorDetermined || 'transparent' }}
                    />
                )}
                {!!expandable && rowExpandable >= 0 && (
                    <td>
                        {!!rowExpandable && (
                            <LemonButton
                                type={isRowExpanded ? 'highlighted' : 'stealth'}
                                onClick={() => {
                                    setIsRowExpanded(!isRowExpanded)
                                    if (isRowExpanded) {
                                        expandable?.onRowCollapse?.(record)
                                    } else {
                                        expandable?.onRowExpand?.(record)
                                    }
                                }}
                                icon={isRowExpanded ? <IconUnfoldLess /> : <IconUnfoldMore />}
                                title={isRowExpanded ? 'Show less' : 'Show more'}
                            />
                        )}
                    </td>
                )}
                {columnGroups.flatMap((columnGroup, columnGroupIndex) =>
                    columnGroup.children.map((column, columnIndex) => {
                        const columnKeyRaw = column.key || column.dataIndex
                        const columnKeyOrIndex = columnKeyRaw ? String(columnKeyRaw) : columnIndex
                        const value = column.dataIndex ? record[column.dataIndex] : undefined
                        const contents = column.render ? column.render(value as T[keyof T], record, recordIndex) : value
                        const areContentsCellRepresentations: boolean =
                            !!contents && typeof contents === 'object' && !React.isValidElement(contents)

                        const key = `LemonTable-td-${columnGroupIndex}-${columnKeyOrIndex}`
                        const props = {
                            className: clsx(
                                columnIndex === columnGroup.children.length - 1 && 'LemonTable__boundary',
                                column.className
                            ),
                            style: { textAlign: column.align } as React.CSSProperties,
                        }

                        if (isScrollable && fixedWidths && column.isFixed) {
                            let result = 0
                            for (const [index, width] of Object.entries(fixedWidths)) {
                                if (parseInt(index) < columnIndex) {
                                    result += width
                                }
                            }
                            props.style = { ...props.style, left: result }
                            props.className = clsx(
                                'LemonTable__sticky',
                                lastFixedIndex &&
                                    lastFixedIndex[0] === columnGroupIndex &&
                                    lastFixedIndex[1] === columnIndex &&
                                    'LemonTable__sticky--boundary'
                            )
                        }
                        const content = areContentsCellRepresentations
                            ? (contents as TableCellRepresentation).children
                            : contents
                        return isScrollable && isFixedRow && column.isFixed ? (
                            <FixedColumn key={key} index={columnIndex} {...props}>
                                {content}
                            </FixedColumn>
                        ) : (
                            <td key={key} {...props}>
                                {content}
                            </td>
                        )
                    })
                )}
            </tr>

            {expandable && !!rowExpandable && isRowExpanded && (
                <tr className="LemonTable__expansion">
                    {!expandable.noIndent && <td />}
                    <td
                        colSpan={
                            columnGroups.reduce((acc, columnGroup) => acc + columnGroup.children.length, 0) +
                            Number(!!expandable.noIndent)
                        }
                    >
                        {expandable.expandedRowRender(record, recordIndex)}
                    </td>
                </tr>
            )}
        </>
    )
    if (isFixedRow) {
        return (
            <FixedLegendsContextProvider columnGroups={columnGroups} onChange={setFixedWidths}>
                {row}
            </FixedLegendsContextProvider>
        )
    } else {
        return row
    }
}
// Without `memo` all rows get rendered when anything in the parent component (LemonTable) changes.
// This was most jarring when scrolling thet table from the very left or the very right – the simple addition
// of a class indicating that scrollability to `table` caused the component to lag due to unneded rerendering of rows.
export const TableRow = React.memo(TableRowRaw) as typeof TableRowRaw

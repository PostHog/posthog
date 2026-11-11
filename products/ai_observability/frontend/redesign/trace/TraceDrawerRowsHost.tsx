import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { MouseEventHandler, useCallback, useEffect } from 'react'

import { TRACE_DRAWER_LISTS, TraceDrawerListId } from './traceDrawerLists'
import { traceDrawerLogic } from './traceDrawerLogic'
import { TRACE_DRAWER_OPEN_ROW_CLASS, opensTraceDrawer } from './traceDrawerRows'
import { TraceListRow } from './traceListRows'

export interface TraceDrawerRowProps {
    className?: string
    onClickCapture?: MouseEventHandler<HTMLElement>
}

export interface TraceDrawerRows {
    isEnabled: boolean
    openTraceId: string | null
    rowProps: (row: TraceListRow | null) => TraceDrawerRowProps
}

export function useTraceDrawerRows(listId: TraceDrawerListId, linkSelector: string): TraceDrawerRows {
    const logic = traceDrawerLogic({ listId })
    const { isEnabled, openTraceId } = useValues(logic)
    const { openRow } = useActions(logic)
    const { rowClick } = TRACE_DRAWER_LISTS[listId]

    const rowProps = useCallback(
        (row: TraceListRow | null): TraceDrawerRowProps => {
            if (!row || !isEnabled) {
                return {}
            }
            return {
                className: clsx(
                    rowClick && 'cursor-pointer',
                    row.traceId === openTraceId && TRACE_DRAWER_OPEN_ROW_CLASS
                ),
                onClickCapture: (event) => {
                    if (opensTraceDrawer(event, linkSelector, rowClick)) {
                        event.preventDefault()
                        event.stopPropagation()
                        // A row cannot take focus, and the panel gives focus back to what held it on opening.
                        event.currentTarget.querySelector<HTMLElement>(linkSelector)?.focus({ preventScroll: true })
                        openRow(row)
                    }
                },
            }
        },
        [isEnabled, linkSelector, openRow, openTraceId, rowClick]
    )

    return { isEnabled, openTraceId, rowProps }
}

export interface TraceDrawerTableProps<T> {
    onRow: (record: T) => TraceDrawerRowProps
    onSortedRowsChange: (records: T[]) => void
}

/** Props for a `LemonTable`. `toRow` needs a stable identity, and returns null for a record with no trace. */
export function useTraceDrawerTable<T>(
    listId: TraceDrawerListId,
    linkSelector: string,
    toRow: (record: T) => TraceListRow | null
): TraceDrawerTableProps<T> {
    const { rowProps } = useTraceDrawerRows(listId, linkSelector)
    const { setRows } = useActions(traceDrawerLogic({ listId }))

    const onRow = useCallback((record: T): TraceDrawerRowProps => rowProps(toRow(record)), [rowProps, toRow])
    const onSortedRowsChange = useCallback(
        (records: T[]): void => setRows(records.map(toRow).filter((row) => row !== null)),
        [setRows, toRow]
    )

    return { onRow, onSortedRowsChange }
}

export interface TraceDrawerRowsSyncProps {
    listId: TraceDrawerListId
    rows: TraceListRow[]
}

export function TraceDrawerRowsSync({ listId, rows }: TraceDrawerRowsSyncProps): null {
    const { setRows } = useActions(traceDrawerLogic({ listId }))

    useEffect(() => {
        setRows(rows)
    }, [rows, setRows])

    return null
}

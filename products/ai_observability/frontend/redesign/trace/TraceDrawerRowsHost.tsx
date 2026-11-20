import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'
import { MouseEventHandler, useCallback, useEffect } from 'react'

import { withRawParams } from './rawSearchParam'
import { TRACE_DRAWER_LISTS, TraceDrawerListId } from './traceDrawerLists'
import { toFullPageUrl, traceDrawerLogic } from './traceDrawerLogic'
import { TRACE_DRAWER_OPEN_ROW_CLASS, opensTraceDrawer, withoutTraceDrawerParams } from './traceDrawerRows'
import { TraceListRow } from './traceListRows'

export interface TraceDrawerRowProps {
    className?: string
    onClickCapture?: MouseEventHandler<HTMLElement>
}

export interface TraceDrawerRows {
    openTraceId: string | null
    rowProps: (row: TraceListRow | null) => TraceDrawerRowProps
}

export function useTraceDrawerRows(
    listId: TraceDrawerListId,
    linkSelector: string,
    navigationRows?: TraceListRow[]
): TraceDrawerRows {
    const logic = traceDrawerLogic({ listId })
    const { openTraceId, openRef } = useValues(logic)
    const { openRow, setRows } = useActions(logic)
    const { rowClick } = TRACE_DRAWER_LISTS[listId]

    const rowProps = useCallback(
        (row: TraceListRow | null): TraceDrawerRowProps => {
            if (!row) {
                return {}
            }
            return {
                className: clsx(
                    rowClick && 'cursor-pointer',
                    row.traceId === openTraceId &&
                        (row.stepId === null || row.stepId === openRef?.stepId) &&
                        TRACE_DRAWER_OPEN_ROW_CLASS
                ),
                onClickCapture: (event) => {
                    if (opensTraceDrawer(event, linkSelector, rowClick)) {
                        event.preventDefault()
                        event.stopPropagation()
                        // A row cannot take focus, and the panel gives focus back to what held it on opening.
                        event.currentTarget.querySelector<HTMLElement>(linkSelector)?.focus({ preventScroll: true })
                        if (navigationRows) {
                            setRows(navigationRows)
                        }
                        openRow(row)
                    }
                },
            }
        },
        [linkSelector, openRow, openTraceId, openRef?.stepId, rowClick, navigationRows, setRows]
    )

    return { openTraceId, rowProps }
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

/**
 * The full page of a row's trace, for the link a modified click opens. It reads only the list's own params, so its
 * identity holds while the drawer opens and steps.
 */
export function useTraceFullPageHref(listId: TraceDrawerListId): (row: TraceListRow) => string {
    const { location, searchParams } = useValues(router)
    const listUrl = combineUrl(
        location.pathname,
        withoutTraceDrawerParams(withRawParams(searchParams, location.search))
    ).url

    return useCallback(
        (row: TraceListRow): string => {
            const { pathname, search, searchParams } = combineUrl(listUrl)
            return toFullPageUrl(row, null, TRACE_DRAWER_LISTS[listId], { pathname, search }, searchParams)
        },
        [listId, listUrl]
    )
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

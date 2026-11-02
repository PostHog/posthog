import type { MouseEvent } from 'react'

import { objectsEqual } from 'lib/utils/objects'

export const TRACE_DRAWER_OPEN_ROW_CLASS = 'LemonTable__row--status-highlighted'

export const TRACE_DRAWER_PARAMS = ['trace', 'ts', 'step']

export function withoutTraceDrawerParams<T>(params: Record<string, T>): Record<string, T> {
    return Object.fromEntries(Object.entries(params).filter(([name]) => !TRACE_DRAWER_PARAMS.includes(name)))
}

interface ListLocation {
    pathname: string
    searchParams: Record<string, unknown>
}

export function changedOnlyTraceDrawerParams(previous: ListLocation, next: ListLocation): boolean {
    return (
        previous.pathname === next.pathname &&
        TRACE_DRAWER_PARAMS.some((name) => previous.searchParams[name] !== next.searchParams[name]) &&
        objectsEqual(withoutTraceDrawerParams(previous.searchParams), withoutTraceDrawerParams(next.searchParams))
    )
}

// Cells with their own link or button (ID, trace name, person) handle their own clicks.
export function hasOwnClickHandler(target: EventTarget | null): boolean {
    return target instanceof Element && !!target.closest('button, a, [role="button"]')
}

export function opensTraceDrawer(
    {
        target,
        currentTarget,
        button,
        metaKey,
        ctrlKey,
        shiftKey,
        altKey,
    }: Pick<MouseEvent, 'target' | 'currentTarget' | 'button' | 'metaKey' | 'ctrlKey' | 'shiftKey' | 'altKey'>,
    linkSelector: string,
    rowClick: boolean
): boolean {
    // React capture also reaches the row from a portal, so an overlay opened from a cell would lose its own clicks.
    const isInsideRow = target instanceof Node && currentTarget.contains(target)
    const isPlainClick = button === 0 && !metaKey && !ctrlKey && !shiftKey && !altKey
    const isTraceLink = target instanceof Element && !!target.closest(linkSelector)
    return isInsideRow && isPlainClick && (isTraceLink || (rowClick && !hasOwnClickHandler(target)))
}

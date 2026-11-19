/** A value of a row that loads after the row, such as its person, previews or sentiment. */
export type TraceCellLoad<T> = { status: 'loading' } | { status: 'ready'; value: T } | { status: 'error' }

export type TraceCellStatus = TraceCellLoad<unknown>['status']

export type CellLoads<T> = ReadonlyMap<string, TraceCellLoad<T>>

// A value on screen stays there while it is read again, as the rows do on a reload.
export function withRequested<T>(loads: CellLoads<T>, ids: string[]): CellLoads<T> {
    const next = new Map(loads)
    for (const id of ids) {
        if (next.get(id)?.status !== 'ready') {
            next.set(id, { status: 'loading' })
        }
    }
    return next
}

export function withFailed<T>(loads: CellLoads<T>, ids: string[]): CellLoads<T> {
    const next = new Map(loads)
    for (const id of ids) {
        if (next.get(id)?.status === 'loading') {
            next.set(id, { status: 'error' })
        }
    }
    return next
}

export function withLoaded<T>(loads: CellLoads<T>, values: [id: string, value: T][]): CellLoads<T> {
    const next = new Map(loads)
    for (const [id, value] of values) {
        next.set(id, { status: 'ready', value })
    }
    return next
}

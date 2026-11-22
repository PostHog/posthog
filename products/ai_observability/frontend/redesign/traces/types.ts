/** A value of a row that loads after the row, such as its person, previews or sentiment. */
export type TraceCellLoad<T> = { status: 'loading' } | { status: 'ready'; value: T } | { status: 'error' }

export type TraceCellStatus = TraceCellLoad<unknown>['status']

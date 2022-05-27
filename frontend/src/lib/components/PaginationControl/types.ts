export interface PaginationBase {
    /** By default pagination is only shown when there are multiple pages, but will always be if this is `false`. */
    hideOnSinglePage?: boolean
}

export interface PaginationAuto extends PaginationBase {
    controlled?: false
    /** Size of each page (except the last one which can be smaller). */
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

export type PaginationState<T> = {
    pagination: PaginationAuto | PaginationManual | undefined
    /**
     * Page adjusted for `pageCount` possibly having gotten smaller since last page param update.
     * Note: `pageCount` can logically only be null if pagination is controlled.
     */
    currentPage: number | null
    /** Push a new browing history item to keep track of the current page. */
    setCurrentPage: (newPage: number) => void
    currentStartIndex: number
    currentEndIndex: number
    /** Contents of the current page. */
    dataSourcePage: T[]
    /** Number of pages. */
    pageCount: number | null
    /** Number of entries in total. */
    entryCount: number | null
}

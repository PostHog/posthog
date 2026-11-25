import type { ListTableState } from './components/ListTable'
import type { ListFilters } from './listFiltersLogic'

/** A page of a list that is read a cursor at a time. */
export interface CursorPage<Item> {
    items: Item[]
    nextCursor: string | null
}

interface CursorParams {
    cursor?: string
}

/** What a request for the next page needs from the list's state. */
export interface NextPageState<Page, Params> {
    pages: Page[]
    pageIndex: number
    pagesParams: Params | null
    pageLoading: boolean
}

export type NextPageStep<Params> = { show: number } | { load: Params } | null

export function appendedPages<Page>(pages: Page[], page: Page, payload: CursorParams | undefined): Page[] {
    return payload?.cursor ? [...pages, page] : [page]
}

export function pageIndexAfterLoad(pageIndex: number, payload: CursorParams | undefined): number {
    return payload?.cursor ? pageIndex + 1 : 0
}

// The params of the first page in memory. A next page reads with them, not with filters typed since.
export function firstPageParams<Params extends CursorParams>(
    current: Params | null,
    payload: Params | undefined
): Params | null {
    return payload && !payload.cursor ? payload : current
}

export function shownPageOf<Page>(pages: Page[], pageIndex: number): Page | null {
    return pages[pageIndex] ?? null
}

export function itemsOf<Item>(shownPage: CursorPage<Item> | null): Item[] {
    return shownPage?.items ?? []
}

// A page that lands moves the index on from where it was requested, so stepping back meanwhile would undo it.
export function canStepBack(pageIndex: number, pageLoading: boolean): boolean {
    return pageIndex > 0 && !pageLoading
}

export function canStepForward(shownPage: CursorPage<unknown> | null): boolean {
    return !!shownPage?.nextCursor
}

export function isRefreshing(pageLoading: boolean, pages: unknown[]): boolean {
    return pageLoading && pages.length > 0
}

export function listStateOf<Params>(
    pages: CursorPage<unknown>[],
    pageFailed: boolean,
    pagesParams: Params | null,
    narrowsSelection: (params: Params | null) => boolean
): ListTableState {
    const firstPage = pages[0]
    if (!firstPage) {
        return pageFailed ? 'error' : 'loading'
    }
    // A page can come back with no rows and still have rows after it, when the server leaves out rows it cannot show.
    if (firstPage.items.length === 0 && !firstPage.nextCursor) {
        return narrowsSelection(pagesParams) ? 'empty-filtered' : 'empty'
    }
    return 'ready'
}

/** Shows a page already in memory, reads the next one, or does nothing while a read is in flight. */
export function nextPageStep<Page extends CursorPage<unknown>, Params extends CursorParams>({
    pages,
    pageIndex,
    pagesParams,
    pageLoading,
}: NextPageState<Page, Params>): NextPageStep<Params> {
    if (pages[pageIndex + 1]) {
        return { show: pageIndex + 1 }
    }
    const cursor = pages[pageIndex]?.nextCursor
    // A read in flight is either this next page or a first page that replaces the pages.
    return cursor && pagesParams && !pageLoading ? { load: { ...pagesParams, cursor } } : null
}

// A kea logic's `cache`, which carries the disposables manager.
type PageRequestCache = Record<string, any>

/**
 * Reads a page that the next read and the unmount abort, so a superseded scan frees its query slot. A hidden tab keeps
 * it, so coming back shows no failed load. `breakpoint` drops the answer, or the failure, of a superseded read.
 */
export async function readAbortablePage<Page>(
    cache: PageRequestCache,
    read: (signal: AbortSignal) => Promise<Page>,
    breakpoint: () => void
): Promise<Page> {
    const controller = new AbortController()
    cache.disposables.add(() => () => controller.abort(), 'pageRequest', { pauseOnPageHidden: false })
    const page = await read(controller.signal).catch((error: unknown) => {
        // A superseded request must not show its failure over the newer selection.
        breakpoint()
        throw error
    })
    breakpoint()
    return page
}

export interface ListRequestScope {
    dateFrom: string
    dateTo: string | null
    filterTestAccounts: boolean
    searchEnabled: boolean
}

/** The request params every list shares: the date range, the property filters, test accounts and the search. */
export function listRequestParams(
    filters: ListFilters,
    { dateFrom, dateTo, filterTestAccounts, searchEnabled }: ListRequestScope
): {
    date_from: string
    date_to: string | undefined
    properties: string | undefined
    filter_test_accounts: boolean
    search: string | undefined
} {
    return {
        date_from: dateFrom,
        date_to: dateTo ?? undefined,
        properties: filters.propertyFilters.length > 0 ? JSON.stringify(filters.propertyFilters) : undefined,
        filter_test_accounts: filterTestAccounts,
        search: (searchEnabled && filters.search) || undefined,
    }
}

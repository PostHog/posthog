import type { ListTableState } from '../lists/components/ListTable'
import { ListRequestScope, listRequestParams } from '../lists/cursorPaging'
import type { ListFilters } from '../lists/listFiltersLogic'
import { SelectionNarrowingParams, narrowsSelection } from '../lists/listParams'

export const DIAGNOSTICS_PAGE_SIZE = 50

/** The fields of an errors or tools page that decide what the list shows. */
export interface DiagnosticsPageSummary {
    count: number
    nothingCaptured: boolean
}

export interface DiagnosticsPageRequest<Params> {
    pageIndex: number
    params: Params
}

/** A page with the request it answered, so the pager and the empty state agree with the rows on screen. */
export interface ShownDiagnosticsPage<Page, Params> {
    page: Page
    request: DiagnosticsPageRequest<Params>
}

/**
 * The API value that a URL param names, or null for a value the API does not know. Every tab shares the `view` and
 * `order` params, so a link from another tab can carry a value that means nothing here.
 */
export function enumValue<Value extends string>(values: Record<string, Value>, raw: string | null): Value | null {
    return Object.values(values).find((value) => value === raw) ?? null
}

/**
 * The params of an errors or tools list: the shared list params, the view of its quick filter, and its order when one
 * is chosen, so the API sorts by its own default otherwise.
 */
export function diagnosticsListParams<View extends string, Order extends string>(
    filters: ListFilters,
    scope: Omit<ListRequestScope, 'searchEnabled'>,
    views: Record<string, View>,
    order: Order | null
): ReturnType<typeof listRequestParams> & { view: View | undefined; order?: Order } {
    return {
        ...listRequestParams(filters, { ...scope, searchEnabled: true }),
        view: enumValue(views, filters.quickFilter) ?? undefined,
        ...(order ? { order } : {}),
    }
}

export function diagnosticsListState(
    shown: ShownDiagnosticsPage<DiagnosticsPageSummary, SelectionNarrowingParams> | null,
    pageError: unknown
): ListTableState {
    if (!shown) {
        return pageError ? 'error' : 'loading'
    }
    if (shown.page.count > 0) {
        return 'ready'
    }
    // With nothing ever captured, clearing the filters would show nothing more.
    return !shown.page.nothingCaptured && narrowsSelection(shown.request.params) ? 'empty-filtered' : 'empty'
}

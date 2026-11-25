// pinned: the URL params of one list's order, searches, page and switches, which saved links read
export const LIST_ORDER_PARAM = 'order'
export const ERRORS_SEARCH_PARAM = 'error_search'
export const TOOLS_SEARCH_PARAM = 'tool_search'
export const PEOPLE_SEARCH_PARAM = 'person_search'
export const PEOPLE_OFFSET_PARAM = 'offset'
export const PEOPLE_INCLUDE_ANONYMOUS_PARAM = 'include_anonymous'

/** The request params that narrow a list below everything in its date range. */
export interface SelectionNarrowingParams {
    properties?: string
    search?: string
    view?: string
    filter_test_accounts?: boolean | null
    person_id?: string
    error?: string
    tool?: string
}

export function narrowsSelection(params: SelectionNarrowingParams | null): boolean {
    return !!(
        params?.properties ||
        params?.search ||
        params?.view ||
        params?.filter_test_accounts ||
        params?.person_id ||
        params?.error ||
        params?.tool
    )
}

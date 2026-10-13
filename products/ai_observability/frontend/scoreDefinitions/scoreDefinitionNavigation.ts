export function scorerFiltersFromSearchParams(searchParams: Record<string, unknown>): Record<string, unknown> {
    return Object.fromEntries(
        ['search', 'page', 'kind', 'archived', 'order_by']
            .filter((key) => searchParams[key] !== undefined)
            .map((key) => [key, searchParams[key]])
    )
}

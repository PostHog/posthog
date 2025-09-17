import { DateFilter } from 'lib/components/DateFilter/DateFilter'

import { EventsQuery, HogQLQuery, SessionAttributionExplorerQuery, TracesQuery } from '~/queries/schema/schema-general'
import { isEventsQuery, isHogQLQuery, isSessionAttributionExplorerQuery, isTracesQuery } from '~/queries/utils'

interface DateRangeProps<Q extends EventsQuery | HogQLQuery | SessionAttributionExplorerQuery | TracesQuery> {
    query: Q
    setQuery?: (query: Q) => void
}
export function DateRange<Q extends EventsQuery | HogQLQuery | SessionAttributionExplorerQuery | TracesQuery>({
    query,
    setQuery,
}: DateRangeProps<Q>): JSX.Element | null {
    if (isEventsQuery(query)) {
        return (
            <DateFilter
                dateFrom={query.after ?? undefined}
                dateTo={query.before ?? undefined}
                onChange={(changedDateFrom, changedDateTo) => {
                    const newQuery: Q = {
                        ...query,
                        after: changedDateFrom ?? undefined,
                        before: changedDateTo ?? undefined,
                    }
                    setQuery?.(newQuery)
                }}
            />
        )
    }

    if (isHogQLQuery(query) || isSessionAttributionExplorerQuery(query)) {
        return (
            <DateFilter
                dateFrom={query.filters?.dateRange?.date_from ?? undefined}
                dateTo={query.filters?.dateRange?.date_to ?? undefined}
                onChange={(changedDateFrom, changedDateTo) => {
                    const newQuery: Q = {
                        ...query,
                        filters: {
                            ...query.filters,
                            dateRange: {
                                date_from: changedDateFrom ?? undefined,
                                date_to: changedDateTo ?? undefined,
                            },
                        },
                    }
                    setQuery?.(newQuery)
                }}
            />
        )
    }

    if (isTracesQuery(query)) {
        return (
            <DateFilter
                dateFrom={query.dateRange?.date_from ?? undefined}
                dateTo={query.dateRange?.date_to ?? undefined}
                onChange={(changedDateFrom, changedDateTo) => {
                    const newQuery: Q = {
                        ...query,
                        dateRange: {
                            date_from: changedDateFrom ?? undefined,
                            date_to: changedDateTo ?? undefined,
                        },
                    }
                    setQuery?.(newQuery)
                }}
            />
        )
    }

    return null
}

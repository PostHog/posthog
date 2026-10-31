import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { LemonButtonProps } from 'lib/lemon-ui/LemonButton'

import {
    EventsQuery,
    HogQLQuery,
    SessionAttributionExplorerQuery,
    SessionsQuery,
    TracesQuery,
} from '~/queries/schema/schema-general'
import {
    isEventsQuery,
    isHogQLQuery,
    isSessionAttributionExplorerQuery,
    isSessionsQuery,
    isTracesQuery,
} from '~/queries/utils'

interface DateRangeProps<
    Q extends EventsQuery | HogQLQuery | SessionAttributionExplorerQuery | SessionsQuery | TracesQuery,
> {
    query: Q
    setQuery?: (query: Q) => void
    size?: LemonButtonProps['size']
}
export function DateRange<
    Q extends EventsQuery | HogQLQuery | SessionAttributionExplorerQuery | SessionsQuery | TracesQuery,
>({ query, setQuery, size }: DateRangeProps<Q>): JSX.Element | null {
    if (isEventsQuery(query) || isSessionsQuery(query)) {
        return (
            <DateFilter
                size={size}
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
                allowFixedRangeWithTime
                showJumpToTimestamp
            />
        )
    }

    if (isHogQLQuery(query) || isSessionAttributionExplorerQuery(query)) {
        return (
            <DateFilter
                size={size}
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
                allowFixedRangeWithTime
            />
        )
    }

    if (isTracesQuery(query)) {
        return (
            <DateFilter
                size={size}
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
                allowFixedRangeWithTime
            />
        )
    }

    return null
}

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { DataNode, EventsQuery, HogQLQuery } from '~/queries/schema'
import { isEventsQuery, isHogQLQuery } from '~/queries/utils'

interface DateRangeProps {
    query: DataNode
    setQuery?: (query: EventsQuery | HogQLQuery) => void
}
export function DateRange({ query, setQuery }: DateRangeProps): JSX.Element | null {
    if (isEventsQuery(query)) {
        return (
            <DateFilter
                dateFrom={query.after ?? undefined}
                dateTo={query.before ?? undefined}
                onChange={(changedDateFrom, changedDateTo) => {
                    const newQuery: EventsQuery = {
                        ...query,
                        after: changedDateFrom ?? undefined,
                        before: changedDateTo ?? undefined,
                    }
                    setQuery?.(newQuery)
                }}
            />
        )
    }
    if (isHogQLQuery(query)) {
        return (
            <DateFilter
                size="medium"
                dateFrom={query.filters?.dateRange?.date_from ?? undefined}
                dateTo={query.filters?.dateRange?.date_to ?? undefined}
                onChange={(changedDateFrom, changedDateTo) => {
                    const newQuery: HogQLQuery = {
                        ...query,
                        filters: {
                            ...(query.filters ?? {}),
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
    return null
}

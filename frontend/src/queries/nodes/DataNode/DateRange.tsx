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
                size="medium"
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
                dateFrom={query.filters?.dateFrom ?? undefined}
                dateTo={query.filters?.dateTo ?? undefined}
                onChange={(changedDateFrom, changedDateTo) => {
                    const newQuery: HogQLQuery = {
                        ...query,
                        filters: {
                            ...(query.filters ?? {}),
                            dateFrom: changedDateFrom ?? undefined,
                            dateTo: changedDateTo ?? undefined,
                        },
                    }
                    setQuery?.(newQuery)
                }}
            />
        )
    }
    return null
}

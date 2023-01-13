import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { DataNode, EventsQuery } from '~/queries/schema'
import { isEventsQuery } from '~/queries/utils'

interface DateRangeProps {
    query: DataNode
    setQuery?: (query: EventsQuery) => void
}
export function DateRange({ query, setQuery }: DateRangeProps): JSX.Element | null {
    if (!isEventsQuery(query)) {
        return null
    }

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

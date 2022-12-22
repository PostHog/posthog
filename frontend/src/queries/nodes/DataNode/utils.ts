import { EventsQuery } from '~/queries/schema'
import { removeExpressionComment } from '~/queries/nodes/DataTable/utils'

export function getNextQuery(query: EventsQuery): EventsQuery | null {
    if (!query.response) {
        return null
    }
    const sortKey = query.orderBy?.[0] ?? '-timestamp'

    // Anything else currently not supported
    if (sortKey !== '-timestamp') {
        return null
    }
    const sortColumnIndex = query.select.map((hql) => removeExpressionComment(hql)).indexOf('timestamp')
    if (sortColumnIndex === -1) {
        return null
    }
    const lastTimestamp = query.response.results[query.response.results.length - 1][sortColumnIndex]

    return { ...query, before: lastTimestamp }
}

import { DataNode } from './schema'
import { isEventsNode, isLegacyQuery } from './utils'
import api from 'lib/api'
import { getCurrentTeamId } from 'lib/utils/logics'
import {
    filterTrendsClientSideParams,
    isFunnelsFilter,
    isLifecycleFilter,
    isPathsFilter,
    isRetentionFilter,
    isStickinessFilter,
    isTrendsFilter,
} from 'scenes/insights/sharedUtils'
import { toParams } from 'lib/utils'

export async function query<N extends DataNode>(
    query: N,
    teamId: number = getCurrentTeamId(),
    abortSignal?: AbortSignal
): Promise<N['response']> {
    if (isLegacyQuery(query)) {
        const { filters } = query
        if (isTrendsFilter(filters) || isStickinessFilter(filters) || isLifecycleFilter(filters)) {
            return await api.get(
                `api/projects/${teamId}/insights/trend/?${toParams(filterTrendsClientSideParams(filters))}`,
                { signal: abortSignal }
            )
        } else if (isRetentionFilter(filters)) {
            return await api.get(`api/projects/${teamId}/insights/retention/?${toParams(filters)}`, {
                signal: abortSignal,
            })
        } else if (isFunnelsFilter(filters)) {
            // @ts-expect-error "refresh" is not part of FilterType, but is here anyway
            const { refresh, ...bodyParams } = filters
            return await api.create(
                `api/projects/${teamId}/insights/funnel/${refresh ? '?refresh=true' : ''}`,
                bodyParams,
                { signal: abortSignal }
            )
        } else if (isPathsFilter(filters)) {
            return await api.create(`api/projects/${teamId}/insights/path`, filters, { signal: abortSignal })
        } else {
            throw new Error(`Cannot load insight of type ${filters.insight}`)
        }
    } else if (isEventsNode(query)) {
        return await api.events.list({ properties: query.properties })
    }
    return await api.create(`api/projects/${teamId}/query/`, { query }, { signal: abortSignal })
}

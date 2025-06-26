import { RetentionTableAppearanceType, RetentionTablePeoplePayload } from 'scenes/retention/types'

import { performQuery } from '~/queries/query'
import { ActorsQuery, NodeKind, RetentionQuery } from '~/queries/schema/schema-general'
import { setLatestVersionsOnQuery } from '~/queries/utils'

export function retentionToActorsQuery(query: RetentionQuery, selectedInterval: number, offset = 0): ActorsQuery {
    const group = query.aggregation_group_type_index != null
    const selectActor = group ? 'group' : 'person'
    const totalIntervals = query.retentionFilter.totalIntervals || 7
    const periodName = query.retentionFilter.period?.toLowerCase() ?? 'day'
    const selects = Array.from({ length: totalIntervals }, (_, intervalNumber) => `${periodName}_${intervalNumber}`)
    return setLatestVersionsOnQuery(
        {
            kind: NodeKind.ActorsQuery,
            select: [selectActor, ...selects],
            orderBy: ['length(appearances) DESC', 'actor_id'],
            source: setLatestVersionsOnQuery(
                {
                    kind: NodeKind.InsightActorsQuery,
                    interval: selectedInterval,
                    source: {
                        ...query,
                        retentionFilter: {
                            ...query.retentionFilter,
                        },
                    },
                },
                { recursion: false }
            ),
            offset,
            limit: offset ? offset * 2 : undefined,
        },
        { recursion: false }
    )
}

export async function queryForActors(
    retentionQuery: RetentionQuery,
    selectedInterval: number,
    offset: number = 0
): Promise<RetentionTablePeoplePayload> {
    const actorsQuery = retentionToActorsQuery(retentionQuery, selectedInterval, offset)
    const response = await performQuery(actorsQuery)
    const results: RetentionTableAppearanceType[] = response.results.map((row) => ({
        person: row[0],
        appearances: row.slice(1, row.length),
    }))
    return {
        result: results,
        offset: response.hasMore ? response.offset + response.limit : undefined,
        missing_persons: response.missing_actors_count,
    }
}

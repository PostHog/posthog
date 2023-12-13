import { RetentionTableAppearanceType, RetentionTablePeoplePayload } from 'scenes/retention/types'

import { query } from '~/queries/query'
import { NodeKind, PersonsQuery, RetentionQuery } from '~/queries/schema'

export function retentionToActorsQuery(query: RetentionQuery, selectedInterval: number, offset = 0): PersonsQuery {
    return {
        kind: NodeKind.PersonsQuery,
        select: ['person', 'appearances'],
        orderBy: ['appearances_count DESC', 'actor_id'],
        source: {
            kind: NodeKind.InsightPersonsQuery,
            source: {
                ...query,
                retentionFilter: {
                    ...query.retentionFilter,
                    selected_interval: selectedInterval,
                },
            },
        },
        offset,
        limit: offset ? offset * 2 : undefined,
    }
}

function appearances_1s_0s(appearances: number[], totalIntervals: number, selectedInterval: number | null): number[] {
    const newTotalIntervals = totalIntervals - (selectedInterval ?? 0)
    return Array.from({ length: newTotalIntervals }, (_, intervalNumber) =>
        appearances.includes(intervalNumber) ? 1 : 0
    )
}

export async function queryForActors(
    retentionQuery: RetentionQuery,
    selectedInterval: number,
    offset: number = 0
): Promise<RetentionTablePeoplePayload> {
    const actorsQuery = retentionToActorsQuery(retentionQuery, selectedInterval, offset)
    const response = await query(actorsQuery)
    const results: RetentionTableAppearanceType[] = response.results.map((row) => ({
        person: row[0],
        appearances: appearances_1s_0s(row[1], retentionQuery.retentionFilter.total_intervals || 11, selectedInterval),
    }))
    return {
        results: results,
        offset: response.hasMore ? response.offset + response.limit : undefined,
        missing_persons: response.missing_actors_count,
    }
}

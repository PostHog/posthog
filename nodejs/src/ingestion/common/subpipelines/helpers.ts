import { OkResultWithContext } from '~/ingestion/framework/pipeline.interface'
import { EventHeaders, Team } from '~/types'

/**
 * Helper for `filterMap` after team resolution: lifts the resolved team from
 * the OK result value into the pipeline context, so downstream `teamAware`
 * blocks can read `context.team`.
 */
export function addTeamToContext<T extends { team: Team }, C>(
    element: OkResultWithContext<T, C>
): OkResultWithContext<T, C & { team: Team }> {
    return {
        result: element.result,
        context: {
            ...element.context,
            team: element.result.value.team,
        },
    }
}

/**
 * Group key for partitioning events within a batch by `(token, distinct_id)`.
 * Used by `concurrentlyPerGroup` to ensure events for the same distinct id are
 * processed sequentially (preserves person/event ordering) while different
 * distinct ids run concurrently.
 */
export function getTokenAndDistinctId(input: {
    headers: EventHeaders
    event: { distinct_id?: string | null }
}): string {
    const token = input.headers.token ?? ''
    const distinctId = input.event.distinct_id ?? ''
    return `${token}:${distinctId}`
}

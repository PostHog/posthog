import { logger } from '~/common/utils/logger'
import { TeamManager } from '~/common/utils/team-manager'
import { PipelineResult, ok } from '~/ingestion/framework/results'
import { EventHeaders } from '~/types'

type PrefetchTeamsStepInput = { headers: EventHeaders }

/**
 * Warms the team cache for all tokens in the chunk with one batched query,
 * instead of a single-row fetch per token when resolveTeamStep walks the
 * events sequentially. Fire-and-forget: the team lazy loader coalesces the
 * per-event lookups issued while this load is in flight onto the same
 * promise, so they fail together with it and resolveTeamStep handles the
 * error. The catch below only keeps the discarded copy of the rejection from
 * becoming an unhandled rejection.
 */
export function prefetchTeamsStep<T extends PrefetchTeamsStepInput>(teamManager: TeamManager, enabled: boolean) {
    return function prefetchTeamsStep(events: T[]): Promise<PipelineResult<T>[]> {
        if (enabled && events.length > 0) {
            const tokens = new Set<string>()
            for (const event of events) {
                if (event.headers.token) {
                    tokens.add(event.headers.token)
                }
            }
            if (tokens.size > 0) {
                void teamManager.getTeamsByTokens([...tokens]).catch((error) => {
                    // Recover only on an explicit retriable error. An unflagged error, such as a
                    // broken query, rethrows and crashes loudly rather than being masked.
                    if (error?.isRetriable === true) {
                        logger.warn('⚠️', 'prefetchTeams failed on a retriable error', { error: String(error) })
                        return
                    }
                    throw error
                })
            }
        }
        return Promise.resolve(events.map((event) => ok(event)))
    }
}

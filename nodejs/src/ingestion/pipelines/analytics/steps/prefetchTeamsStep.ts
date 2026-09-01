import { TeamManager } from '~/common/utils/team-manager'
import { createPrefetchStep } from '~/ingestion/pipelines/analytics/steps/createPrefetchStep'
import { EventHeaders } from '~/types'

type PrefetchTeamsStepInput = { headers: EventHeaders }

/** Warms the team cache for the chunk's tokens ahead of resolveTeamStep's per-event lookups. */
export function prefetchTeamsStep<T extends PrefetchTeamsStepInput>(teamManager: TeamManager, enabled: boolean) {
    return createPrefetchStep<T, string>({
        name: 'prefetchTeamsStep',
        extractKey: (event) => event.headers.token || undefined,
        load: (tokens) => teamManager.getTeamsByTokens(tokens, { flush: true }),
        enabled,
    })
}

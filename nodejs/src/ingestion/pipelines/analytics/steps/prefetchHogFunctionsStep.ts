import { HogTransformer } from '~/common/hog-transformations/hog-transformer.interface'
import { createPrefetchStep } from '~/ingestion/pipelines/analytics/steps/createPrefetchStep'
import { Team } from '~/types'

type PrefetchHogFunctionsStepInput = { team: Pick<Team, 'id'> }

/** Warms the transformation hog-function cache for the chunk's teams ahead of the hog transformer's per-event lookups. */
export function prefetchHogFunctionsStep<T extends PrefetchHogFunctionsStepInput>(
    hogTransformer: Pick<HogTransformer, 'prefetchHogFunctionsForTeams'>,
    enabled: boolean
) {
    return createPrefetchStep<T, number>({
        name: 'prefetchHogFunctionsStep',
        extractKey: (event) => event.team.id,
        load: (teamIds) => hogTransformer.prefetchHogFunctionsForTeams(teamIds),
        enabled,
    })
}

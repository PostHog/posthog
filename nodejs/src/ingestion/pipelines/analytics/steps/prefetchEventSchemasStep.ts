import { EventSchemaEnforcementManager } from '~/common/utils/event-schema-enforcement-manager'
import { createPrefetchStep } from '~/ingestion/pipelines/analytics/steps/createPrefetchStep'
import { Team } from '~/types'

type PrefetchEventSchemasStepInput = { team: Pick<Team, 'id'> }

/** Warms the enforced-schema cache for the chunk's teams ahead of validateEventSchemaStep's per-event lookups. */
export function prefetchEventSchemasStep<T extends PrefetchEventSchemasStepInput>(
    eventSchemaEnforcementManager: Pick<EventSchemaEnforcementManager, 'getSchemasForTeams'>,
    enabled: boolean
) {
    return createPrefetchStep<T, number>({
        name: 'prefetchEventSchemasStep',
        extractKey: (event) => event.team.id,
        load: (teamIds) => eventSchemaEnforcementManager.getSchemasForTeams(teamIds, { flush: true }),
        enabled,
    })
}

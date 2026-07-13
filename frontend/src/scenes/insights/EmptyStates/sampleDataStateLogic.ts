import { connect, kea, path, selectors } from 'kea'

import { teamLogic } from 'scenes/teamLogic'

import { isSharedView } from '~/exporter/exporterViewLogic'

import type { sampleDataStateLogicType } from './sampleDataStateLogicType'

/**
 * Gates the pre-ingestion sample-data placeholder: only projects that never ingested an event see
 * it. The wizard setup status shown on the placeholder comes from `setupWizardStatusLogic`.
 */
export const sampleDataStateLogic = kea<sampleDataStateLogicType>([
    path(['scenes', 'insights', 'EmptyStates', 'sampleDataStateLogic']),
    connect(() => ({
        values: [teamLogic, ['currentTeam']],
    })),
    selectors({
        shouldShowSampleData: [
            (s) => [s.currentTeam],
            // Never show the placeholder in shared/embedded/exported views: `TeamPublicSerializer`
            // omits `ingested_event`, so it reads as `undefined` and would otherwise falsely flag
            // every empty tile on a real, data-carrying project as "never ingested". External
            // viewers should just see the normal "No data" state.
            (currentTeam): boolean =>
                !isSharedView() && !!currentTeam && !currentTeam.ingested_event && !currentTeam.is_demo,
        ],
    }),
])

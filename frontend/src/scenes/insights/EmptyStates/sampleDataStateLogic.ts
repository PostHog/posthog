import { connect, kea, path, selectors } from 'kea'

import { teamLogic } from 'scenes/teamLogic'

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
            (currentTeam): boolean => !!currentTeam && !currentTeam.ingested_event && !currentTeam.is_demo,
        ],
    }),
])

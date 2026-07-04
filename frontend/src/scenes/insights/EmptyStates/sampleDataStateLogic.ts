import { connect, kea, path, selectors } from 'kea'

import { teamLogic } from 'scenes/teamLogic'

import { getCurrentExporterData } from '~/exporter/exporterViewLogic'

import type { sampleDataStateLogicType } from './sampleDataStateLogicType'

/**
 * Gates the pre-ingestion sample-data placeholder: only projects that never ingested an event see
 * it. The wizard setup status shown on the placeholder comes from `setupWizardStatusLogic`.
 *
 * Never shown on shared/exported pages: the viewer there isn't the project owner, the "install
 * PostHog" guidance is meaningless to them, and rendering it would mount the wizard status logic,
 * which calls team-scoped APIs an unauthenticated visitor is not allowed to hit.
 */
export const sampleDataStateLogic = kea<sampleDataStateLogicType>([
    path(['scenes', 'insights', 'EmptyStates', 'sampleDataStateLogic']),
    connect(() => ({
        values: [teamLogic, ['currentTeam']],
    })),
    selectors({
        shouldShowSampleData: [
            (s) => [s.currentTeam],
            (currentTeam): boolean =>
                !getCurrentExporterData() && !!currentTeam && !currentTeam.ingested_event && !currentTeam.is_demo,
        ],
    }),
])

import { connect, kea, path, selectors } from 'kea'

import { activeCloudRunLogic } from 'scenes/onboarding/shared/wizard-sync/activeCloudRunLogic'
import { wizardActiveSessionDetectorLogic } from 'scenes/onboarding/shared/wizard-sync/wizardActiveSessionDetectorLogic'
import { wizardSyncUiLogic } from 'scenes/onboarding/shared/wizard-sync/wizardSyncUiLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import type { installationStatusNavLogicType } from './installationStatusNavLogicType'

export type NavInstallationPhase = 'running' | 'completed' | 'error' | 'connecting' | 'idle'

/**
 * Coordinates whether to show an "Installation status" item in the sidebar footer,
 * and what label / badge tone to display.
 *
 * Data sources (all already exist):
 *   - `activeCloudRunLogic.activeCloudRun` — persisted cloud-run handle
 *   - `wizardActiveSessionDetectorLogic.hasActiveSession` — cheap REST poll for local wizard runs
 *   - `teamLogic.hasOnboardedAnyProduct`, `currentTeam.ingested_event` — onboarding relevance
 *   - `wizardSyncUiLogic` — shared dialog state with the floating FAB
 */
export const installationStatusNavLogic = kea<installationStatusNavLogicType>([
    path(['layout', 'panel-layout', 'installationStatusNavLogic']),
    connect(() => ({
        values: [
            activeCloudRunLogic,
            ['activeCloudRun', 'panelMounted'],
            wizardActiveSessionDetectorLogic,
            ['hasActiveSession'],
            teamLogic,
            ['hasOnboardedAnyProduct', 'currentTeam'],
            wizardSyncUiLogic,
            ['dialogOpen'],
        ],
        actions: [wizardSyncUiLogic, ['openDialog']],
    })),
    selectors({
        /** Whether the nav item should render at all. */
        shouldShow: [
            (s) => [s.hasOnboardedAnyProduct, s.currentTeam, s.activeCloudRun, s.hasActiveSession, s.panelMounted],
            (hasOnboardedAnyProduct, currentTeam, activeCloudRun, hasActiveSession, panelMounted): boolean => {
                // Panel-mounted inline progress already shows the run — avoid double-surfacing
                if (panelMounted) {
                    return false
                }
                // Cloud or local run in flight
                if (activeCloudRun || hasActiveSession) {
                    return true
                }
                // Onboarding is still relevant (no events yet, or no product completed)
                if (!hasOnboardedAnyProduct && currentTeam && !currentTeam.ingested_event) {
                    return true
                }
                return false
            },
        ],

        /** Whether an active run (cloud or local) is the reason we're showing. */
        isRunActive: [
            (s) => [s.activeCloudRun, s.hasActiveSession],
            (activeCloudRun, hasActiveSession): boolean => !!(activeCloudRun || hasActiveSession),
        ],

        /** High-level phase for the badge tone: 'running' while in flight, 'idle' for incomplete onboarding. */
        phase: [(s) => [s.isRunActive], (isRunActive): NavInstallationPhase => (isRunActive ? 'running' : 'idle')],

        /** URL to navigate to on click when no run is active. */
        onboardingUrl: [() => [], (): string => urls.onboarding()],
    }),
])

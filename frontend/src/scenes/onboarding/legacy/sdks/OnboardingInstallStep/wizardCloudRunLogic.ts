import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'

import { lemonToast } from '@posthog/lemon-ui'

import api, { ApiError } from 'lib/api'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { IntegrationType, OnboardingStepKey } from '~/types'

import { onboardingLogic } from '../../onboardingLogic'
import { sdksLogic } from '../sdksLogic'
import type { wizardCloudRunLogicType } from './wizardCloudRunLogicType'

export type CloudRunStatus =
    | 'idle' // No request in flight — show connect / repo-pick / start UI.
    | 'submitting' // POST to kick off the run is in flight.
    | 'queued' // Run accepted — the user can keep moving; the FAB carries progress.
    | 'error' // Kickoff failed.

// Shared with the local CLI wizard so the existing session-sync FAB and the
// install-step tracker pick up cloud runs with no extra wiring — a cloud run is
// the same instrumentation workflow, just executed on our infra rather than on
// the user's machine.
export const WIZARD_CLOUD_RUN_WORKFLOW_ID = 'posthog-integration'

/**
 * Drives the "open a PR for me" option on the install step:
 *   - resolves the team's GitHub integration (or the URL to connect one)
 *   - holds the chosen repository
 *   - kicks off the cloud run and tracks its lifecycle
 *
 * Live progress and the "your PR is ready" payoff are not owned here — the cloud
 * run posts wizard sessions under WIZARD_CLOUD_RUN_WORKFLOW_ID, so the existing
 * session-sync surfaces (wizardProgressTrackerLogic + the global FAB) render them
 * automatically. This logic only has to get the run started without blocking the
 * user from continuing onboarding.
 */
export const wizardCloudRunLogic = kea<wizardCloudRunLogicType>([
    path(['scenes', 'onboarding', 'wizardCloudRunLogic']),
    connect(() => ({
        values: [
            integrationsLogic,
            ['integrations'],
            teamLogic,
            ['currentProjectId'],
            onboardingLogic,
            ['currentStepProductKey'],
            sdksLogic,
            ['selectedSDK'],
        ],
        actions: [integrationsLogic, ['loadIntegrations']],
    })),
    actions({
        setSelectedRepository: (repository: string | null) => ({ repository }),
        startCloudRun: true,
        startCloudRunSuccess: true,
        startCloudRunFailure: true,
    }),
    reducers({
        selectedRepository: [
            null as string | null,
            {
                setSelectedRepository: (_, { repository }) => repository,
            },
        ],
        cloudRunStatus: [
            'idle' as CloudRunStatus,
            {
                startCloudRun: () => 'submitting',
                startCloudRunSuccess: () => 'queued',
                startCloudRunFailure: () => 'error',
                // Picking a different repo after a failure clears the error so the
                // primary button is actionable again.
                setSelectedRepository: (state) => (state === 'error' ? 'idle' : state),
            },
        ],
    }),
    selectors({
        githubIntegration: [
            (s) => [s.integrations],
            (integrations: IntegrationType[] | null): IntegrationType | null =>
                integrations?.find((i) => i.kind === 'github') ?? null,
        ],
        isGithubConnected: [(s) => [s.githubIntegration], (githubIntegration): boolean => !!githubIntegration],
        connectGitHubUrl: [
            (s) => [s.currentStepProductKey],
            (currentStepProductKey): string => {
                // Full-page redirect to install/authorize the GitHub App, then back to
                // the install step. integrationsLogic's callback appends the new
                // integration id, and loadIntegrations() repopulates githubIntegration,
                // so the block advances from "connect" to "pick a repo" on return.
                const next = urls.onboarding({
                    productKey: currentStepProductKey ?? undefined,
                    stepKey: OnboardingStepKey.INSTALL,
                })
                return api.integrations.authorizeUrl({ kind: 'github', next })
            },
        ],
        // The cloud wizard auto-detects the framework, so this is a hint rather than a
        // requirement — only set when the user happens to have picked an SDK manually.
        skillId: [(s) => [s.selectedSDK], (selectedSDK): string | undefined => selectedSDK?.key],
    }),
    listeners(({ values, actions }) => ({
        startCloudRun: async () => {
            const { githubIntegration, selectedRepository, currentProjectId, skillId } = values
            if (!githubIntegration || !selectedRepository || !currentProjectId) {
                actions.startCloudRunFailure()
                return
            }
            try {
                // SCAFFOLD: the cloud-run service (clone repo → run the wizard → open a PR
                // via a Temporal workflow) is the follow-up backend piece. It will post
                // progress to the existing wizard/sessions endpoint under
                // WIZARD_CLOUD_RUN_WORKFLOW_ID and stash the opened PR URL in the terminal
                // session's event_plan. Swap this hand-built call for the generated client
                // once that endpoint's serializer lands (see /adopting-generated-api-types).
                await api.create(`api/projects/${currentProjectId}/wizard/cloud_runs`, {
                    integration_id: githubIntegration.id,
                    repository: selectedRepository,
                    workflow_id: WIZARD_CLOUD_RUN_WORKFLOW_ID,
                    skill_id: skillId,
                })
                actions.startCloudRunSuccess()
            } catch (e) {
                const detail = e instanceof ApiError ? e.detail : null
                lemonToast.error(detail || 'Could not start the cloud run. Please try again.')
                actions.startCloudRunFailure()
            }
        },
        startCloudRunSuccess: () => {
            // Non-blocking by design: the user keeps moving through onboarding and the
            // global FAB tells them when the PR lands.
            lemonToast.success("On it – we'll open your pull request and let you know when it's ready.")
        },
    })),
])

import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'

import { lemonToast } from '@posthog/lemon-ui'

import api, { ApiError } from 'lib/api'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { IntegrationType, OnboardingStepKey } from '~/types'

import { onboardingLogic } from '../../legacy/onboardingLogic'
import { sdksLogic } from '../../legacy/sdks/sdksLogic'
import { onboardingEventUsageLogic } from '../../onboardingEventUsageLogic'
import { activeCloudRunLogic } from './activeCloudRunLogic'
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
        actions: [
            integrationsLogic,
            ['loadIntegrations'],
            activeCloudRunLogic,
            ['setActiveCloudRun'],
            onboardingEventUsageLogic,
            ['reportContextOnboardingCloudRunQueued'],
        ],
    })),
    actions({
        setSelectedRepository: (repository: string | null) => ({ repository }),
        startCloudRun: true,
        startCloudRunSuccess: true,
        startCloudRunFailure: true,
        setCloudRunHandle: (taskId: string, runId: string) => ({ taskId, runId }),
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
        // The run handle returned by the kickoff POST. The Installation layer streams progress by run id.
        cloudRunTaskId: [
            null as string | null,
            {
                setCloudRunHandle: (_, { taskId }) => taskId,
            },
        ],
        cloudRunRunId: [
            null as string | null,
            {
                setCloudRunHandle: (_, { runId }) => runId,
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
            const { githubIntegration, selectedRepository, currentProjectId } = values
            if (!githubIntegration || !selectedRepository || !currentProjectId) {
                actions.startCloudRunFailure()
                return
            }
            // The picker holds the bare repo name; the endpoint wants "owner/repo", where the owner
            // is the GitHub integration's account.
            const owner = githubIntegration.config?.account?.name
            const repository =
                selectedRepository.includes('/') || !owner ? selectedRepository : `${owner}/${selectedRepository}`
            try {
                // Kicks off the cloud run (clone repo → run the wizard → open a PR via a Temporal
                // workflow) and returns the run handle. Live progress is surfaced by the Installation
                // layer (installationProgressLogic), which streams this run's TaskRun pipeline merged
                // with the wizard session detail.
                const { task_id, run_id } = await api.create<{ task_id: string; run_id: string; status: string }>(
                    'api/wizard/cloud_run',
                    {
                        project_id: currentProjectId,
                        repository,
                    }
                )
                actions.setCloudRunHandle(task_id, run_id)
                // teamLogic's currentProjectId can be the '@current' placeholder pre-load; by kickoff
                // time the team is loaded, so this is a plain numeric coercion in practice.
                actions.setActiveCloudRun(task_id, run_id, new Date().toISOString(), Number(currentProjectId))
                // Frontend side of the kickoff, pairing with the backend `task_run_created` (GROW-89).
                actions.reportContextOnboardingCloudRunQueued({ taskId: task_id, runId: run_id, repository })
                actions.startCloudRunSuccess()
            } catch (e) {
                const detail = e instanceof ApiError ? e.detail : null
                lemonToast.error(detail || 'Could not start the cloud run. Please try again.')
                actions.startCloudRunFailure()
            }
        },
        startCloudRunSuccess: () => {
            // The POST only queues the run — it isn't done. The real outcome (running → completed/error)
            // is reported by the wizard sync surfaces (inline tracker + FAB) when enabled, so keep this a
            // neutral acknowledgement rather than claiming the PR is on its way.
            lemonToast.info('Cloud run queued')
        },
    })),
])

import { actions, afterMount, connect, getContext, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'

import { activeCloudRunLogic } from 'scenes/onboarding/self-driving/sdks/OnboardingInstallStep/activeCloudRunLogic'
import {
    InstallationProgress,
    installationProgressLogic,
} from 'scenes/onboarding/self-driving/sdks/OnboardingInstallStep/installationProgressLogic'
import { teamLogic } from 'scenes/teamLogic'

import { tasksList, tasksRunsList } from 'products/tasks/frontend/generated/api'
import type { TaskRunDetailDTOApi } from 'products/tasks/frontend/generated/api.schemas'

import type { setupWizardStatusLogicType } from './setupWizardStatusLogicType'

export interface SetupPullRequest {
    url: string
    merged: boolean
}

/** Where the onboarding wizard's setup run is at, coarse enough for any surface to render. */
export type SetupWizardStatus =
    /** The wizard opened a pull request - surface it so the user merges it. */
    | { kind: 'pull_request'; pullRequest: SetupPullRequest }
    /** The wizard is still working on the integration - a PR will follow. */
    | { kind: 'installing' }

export interface SetupRunHandle {
    taskId: string
    runId: string
}

export interface DiscoveredSetupRun {
    status: SetupWizardStatus
    /** Null when the tasks API response carried no run id, so there is nothing to stream. */
    handle: SetupRunHandle | null
}

const RUNNING_STATUSES = ['not_started', 'queued', 'in_progress']

const byCreatedAtDesc = (a: { created_at?: string | null }, b: { created_at?: string | null }): number =>
    (b.created_at ?? '').localeCompare(a.created_at ?? '')

type LatestRunDetail = Pick<TaskRunDetailDTOApi, 'id' | 'status' | 'output' | 'created_at'>

/**
 * The tasks list endpoint nests the full run detail in `latest_run`, but the generated type
 * collapses it to the bare run id (OpenAPI schema-name collision with the conversation envelope
 * variant), so the nested shape has to be recovered with a cast.
 */
function asLatestRunDetail(latestRun: unknown): Partial<LatestRunDetail> | null {
    return latestRun && typeof latestRun === 'object' ? (latestRun as Partial<LatestRunDetail>) : null
}

export function pullRequestFromRunOutput(output: Record<string, unknown> | null | undefined): SetupPullRequest | null {
    const url = output?.pr_url
    if (typeof url !== 'string' || !url) {
        return null
    }
    return { url, merged: output?.pr_merged === true }
}

export function isRunRunning(run: Partial<LatestRunDetail> | null): boolean {
    return typeof run?.status === 'string' && RUNNING_STATUSES.includes(run.status)
}

/**
 * Collapse the live installation progress into the coarse setup status. The stream does not know
 * whether a PR got merged, so `merged` only ever turns true via the REST snapshot.
 */
export function statusFromProgress(progress: InstallationProgress | null): SetupWizardStatus | null {
    if (!progress?.isCurrent) {
        return null
    }
    if (progress.prUrl) {
        return { kind: 'pull_request', pullRequest: { url: progress.prUrl, merged: false } }
    }
    if (progress.phase === 'connecting' || progress.phase === 'running') {
        return { kind: 'installing' }
    }
    return null
}

/**
 * App-wide status of the onboarding wizard's setup task run (the cloud run that installs PostHog
 * in the user's codebase and opens a pull request).
 *
 * Two complementary sources, merged in `setupStatus`:
 *  - REST discovery (`loadDiscoveredRun`): finds the newest onboarding task via the tasks API, so
 *    runs kicked off elsewhere (another browser, before a refresh) are found too. Also the only
 *    source that knows whether the PR got merged.
 *  - Live streaming: when a run handle is known (the persisted `activeCloudRunLogic` handle, or a
 *    still-running discovered run), `installationProgressLogic` is mounted for it and its
 *    normalized progress is mirrored here, so the status updates in real time.
 *
 * Mounting this logic starts the REST discovery and, while a run is live, an SSE stream. Mount it
 * from surfaces that actually need setup state rather than app-wide (INC-886).
 */
export const setupWizardStatusLogic = kea<setupWizardStatusLogicType>([
    path(['scenes', 'onboarding', 'shared', 'setupWizardStatusLogic']),
    connect(() => ({
        values: [teamLogic, ['currentTeamId'], activeCloudRunLogic, ['activeCloudRun']],
    })),
    actions({
        liveProgressUpdated: (progress: InstallationProgress | null) => ({ progress }),
    }),
    loaders(({ values }) => ({
        discoveredRun: [
            null as DiscoveredSetupRun | null,
            {
                loadDiscoveredRun: async (): Promise<DiscoveredSetupRun | null> => {
                    try {
                        const projectId = String(values.currentTeamId)
                        const tasks = await tasksList(projectId, { origin_product: 'onboarding', limit: 10 })
                        const newestFirst = [...tasks.results].sort(byCreatedAtDesc)
                        for (const task of newestFirst) {
                            const run = asLatestRunDetail(task.latest_run)
                            const pullRequest = pullRequestFromRunOutput(run?.output)
                            if (pullRequest) {
                                return {
                                    status: { kind: 'pull_request', pullRequest },
                                    handle: run?.id ? { taskId: task.id, runId: run.id } : null,
                                }
                            }
                        }
                        // Fallback for when `latest_run` really is a bare run id: check the newest task's runs
                        const newestTask = newestFirst[0]
                        if (newestTask && typeof newestTask.latest_run === 'string') {
                            const runs = await tasksRunsList(projectId, newestTask.id)
                            const runsNewestFirst = [...runs.results].sort(byCreatedAtDesc)
                            for (const run of runsNewestFirst) {
                                const pullRequest = pullRequestFromRunOutput(run.output)
                                if (pullRequest) {
                                    return {
                                        status: { kind: 'pull_request', pullRequest },
                                        handle: { taskId: newestTask.id, runId: run.id },
                                    }
                                }
                            }
                            const runningRun = runsNewestFirst.find((run) => isRunRunning(run))
                            if (runningRun) {
                                return {
                                    status: { kind: 'installing' },
                                    handle: { taskId: newestTask.id, runId: runningRun.id },
                                }
                            }
                        }
                        // No PR anywhere: the wizard may still be working on it
                        for (const task of newestFirst) {
                            const run = asLatestRunDetail(task.latest_run)
                            if (isRunRunning(run)) {
                                return {
                                    status: { kind: 'installing' },
                                    handle: run?.id ? { taskId: task.id, runId: run.id } : null,
                                }
                            }
                        }
                        return null
                    } catch {
                        // Consumers work without wizard context: a tasks API failure is non-fatal
                        return null
                    }
                },
            },
        ],
    })),
    reducers({
        liveProgress: [
            null as InstallationProgress | null,
            {
                liveProgressUpdated: (_, { progress }) => progress,
            },
        ],
    }),
    selectors({
        liveRunHandle: [
            (s) => [s.activeCloudRun, s.discoveredRun],
            (activeCloudRun, discoveredRun): SetupRunHandle | null => {
                if (activeCloudRun) {
                    return { taskId: activeCloudRun.taskId, runId: activeCloudRun.runId }
                }
                // Only stream discovered runs that are still going; finished runs are fully described by REST
                return discoveredRun?.status.kind === 'installing' ? discoveredRun.handle : null
            },
        ],
        setupStatus: [
            (s) => [s.liveProgress, s.discoveredRun],
            (liveProgress, discoveredRun): SetupWizardStatus | null => {
                const live = statusFromProgress(liveProgress)
                const discovered = discoveredRun?.status ?? null
                if (live?.kind === 'pull_request') {
                    // Only REST knows whether the PR got merged, so prefer its record of the same PR
                    if (discovered?.kind === 'pull_request' && discovered.pullRequest.url === live.pullRequest.url) {
                        return discovered
                    }
                    return live
                }
                if (live) {
                    return live
                }
                // The live layer watched the run reach a terminal state without a PR: a stale REST
                // "installing" snapshot must not keep claiming the wizard is still at work
                if (
                    liveProgress?.isCurrent &&
                    (liveProgress.phase === 'error' || liveProgress.phase === 'completed') &&
                    discovered?.kind === 'installing'
                ) {
                    return null
                }
                return discovered
            },
        ],
        setupStatusLoading: [(s) => [s.discoveredRunLoading], (discoveredRunLoading): boolean => discoveredRunLoading],
    }),
    subscriptions(({ actions, cache }) => ({
        // installationProgressLogic is keyed by a run id we only know at runtime, so it can't be
        // connected statically. Mount it imperatively for the current handle and mirror its
        // progress selector through a store subscription; disposables tear it all down on unmount.
        liveRunHandle: (handle: SetupRunHandle | null) => {
            const runKey = handle ? `${handle.taskId}:${handle.runId}` : null
            if (runKey === cache.liveRunKey) {
                return
            }
            cache.liveRunKey = runKey
            cache.disposables.dispose('live-progress')
            if (!handle) {
                actions.liveProgressUpdated(null)
                return
            }
            cache.disposables.add(() => {
                const progressLogic = installationProgressLogic.build({
                    mode: 'cloud',
                    runId: handle.runId,
                    taskId: handle.taskId,
                })
                const unmount = progressLogic.mount()
                const { store } = getContext()
                let lastPushed: InstallationProgress | null = null
                const push = (): void => {
                    const progress = progressLogic.selectors.installationProgress(store.getState(), progressLogic.props)
                    if (progress !== lastPushed) {
                        lastPushed = progress
                        actions.liveProgressUpdated(progress)
                    }
                }
                push()
                const unsubscribe = store.subscribe(push)
                return () => {
                    unsubscribe()
                    unmount()
                }
            }, 'live-progress')
        },
    })),
    afterMount(({ actions }) => {
        actions.loadDiscoveredRun()
    }),
])

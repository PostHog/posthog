import { afterMount, connect, kea, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { teamLogic } from 'scenes/teamLogic'

import { tasksList, tasksRunsList } from 'products/tasks/frontend/generated/api'

import type { sampleDataStateLogicType } from './sampleDataStateLogicType'

export interface SetupPullRequest {
    url: string
    merged: boolean
}

/** Where the onboarding wizard's cloud run is at, for the pre-ingestion placeholder. */
export type SetupWizardStatus =
    /** The wizard opened a pull request - surface it so the user merges it. */
    | { kind: 'pull_request'; pullRequest: SetupPullRequest }
    /** The wizard is still working on the integration - a PR will follow. */
    | { kind: 'installing' }

const RUNNING_STATUSES = ['not_started', 'queued', 'in_progress']

const byCreatedAtDesc = (a: { created_at?: string | null }, b: { created_at?: string | null }): number =>
    (b.created_at ?? '').localeCompare(a.created_at ?? '')

/**
 * `latest_run` on the tasks list response nests the full run detail at runtime, but the generated
 * type collapses it to the bare run id (OpenAPI schema-name collision) - so read it defensively,
 * tolerating both shapes.
 */
export function extractPullRequestFromRun(run: unknown): SetupPullRequest | null {
    if (!run || typeof run !== 'object' || !('output' in run)) {
        return null
    }
    const output = (run as { output?: Record<string, unknown> | null }).output
    const url = output?.pr_url
    if (typeof url !== 'string' || !url) {
        return null
    }
    return { url, merged: output?.pr_merged === true }
}

/** Same defensive read as {@link extractPullRequestFromRun}, for the run's execution status. */
export function isRunStillRunning(run: unknown): boolean {
    if (!run || typeof run !== 'object' || !('status' in run)) {
        return false
    }
    const status = (run as { status?: unknown }).status
    return typeof status === 'string' && RUNNING_STATUSES.includes(status)
}

/**
 * Resolves what the onboarding wizard's cloud run is up to (still installing, or opened a pull
 * request), so pre-ingestion placeholder states can point users at the next step. Only loads for
 * teams that have never ingested an event.
 */
export const sampleDataStateLogic = kea<sampleDataStateLogicType>([
    path(['scenes', 'insights', 'EmptyStates', 'sampleDataStateLogic']),
    connect(() => ({
        values: [teamLogic, ['currentTeam', 'currentTeamId']],
    })),
    loaders(({ values }) => ({
        setupStatus: [
            null as SetupWizardStatus | null,
            {
                loadSetupStatus: async (): Promise<SetupWizardStatus | null> => {
                    try {
                        const projectId = String(values.currentTeamId)
                        const tasks = await tasksList(projectId, { origin_product: 'onboarding', limit: 10 })
                        const newestFirst = [...tasks.results].sort(byCreatedAtDesc)
                        for (const task of newestFirst) {
                            const pullRequest = extractPullRequestFromRun(task.latest_run)
                            if (pullRequest) {
                                return { kind: 'pull_request', pullRequest }
                            }
                        }
                        // Fallback for when latest_run really is a bare run id: check the newest task's runs
                        const newestTask = newestFirst[0]
                        if (newestTask && typeof newestTask.latest_run === 'string') {
                            const runs = await tasksRunsList(projectId, newestTask.id)
                            const runsNewestFirst = [...runs.results].sort(byCreatedAtDesc)
                            for (const run of runsNewestFirst) {
                                const pullRequest = extractPullRequestFromRun(run)
                                if (pullRequest) {
                                    return { kind: 'pull_request', pullRequest }
                                }
                            }
                            if (runsNewestFirst.some(isRunStillRunning)) {
                                return { kind: 'installing' }
                            }
                        }
                        // No PR anywhere: the wizard may still be working on it
                        if (newestFirst.some((task) => isRunStillRunning(task.latest_run))) {
                            return { kind: 'installing' }
                        }
                        return null
                    } catch {
                        // The placeholder works without PR context - a tasks API failure is non-fatal
                        return null
                    }
                },
            },
        ],
    })),
    selectors({
        shouldShowSampleData: [
            (s) => [s.currentTeam],
            (currentTeam): boolean => !!currentTeam && !currentTeam.ingested_event && !currentTeam.is_demo,
        ],
    }),
    afterMount(({ actions, values }) => {
        if (values.shouldShowSampleData) {
            actions.loadSetupStatus()
        }
    }),
])

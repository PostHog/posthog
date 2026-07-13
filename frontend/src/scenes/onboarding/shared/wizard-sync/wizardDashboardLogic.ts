import { connect, kea, path } from 'kea'
import { loaders } from 'kea-loaders'

import { projectLogic } from 'scenes/projectLogic'

import { dashboardsList } from 'products/dashboards/frontend/generated/api'
import type { DashboardBasicApi } from 'products/dashboards/frontend/generated/api.schemas'

import type { wizardDashboardLogicType } from './wizardDashboardLogicType'

// The wizard stamps started_at from its own clock (the user's machine or the sandbox), while
// dashboard created_at is server time — tolerate a skewed CLI clock so a dashboard created in the
// first seconds of a run isn't filtered out.
const CLOCK_SKEW_MS = 2 * 60 * 1000

// One page is plenty: detection runs during onboarding, where the project holds at most a handful
// of dashboards. If the wizard's dashboard falls outside this page the CTA silently doesn't show.
const DETECTION_PAGE_SIZE = 100

export interface DetectedDashboard {
    id: number
    name: string | null
}

type DashboardCandidate = Pick<DashboardBasicApi, 'id' | 'name' | 'created_at' | 'deleted' | 'creation_mode'>

/**
 * The dashboard most likely created by the wizard during this run: the newest non-template
 * dashboard created after the run started (with clock-skew tolerance). Heuristic by design — the
 * wizard doesn't report the dashboard it built, so a dashboard the user created mid-run can match.
 * Returns null when nothing plausible exists, in which case no CTA is shown.
 */
export function pickWizardDashboard(dashboards: DashboardCandidate[], startedAt: string): DetectedDashboard | null {
    const startedAtMs = new Date(startedAt).getTime()
    if (Number.isNaN(startedAtMs)) {
        return null
    }
    const cutoff = startedAtMs - CLOCK_SKEW_MS
    const candidates = dashboards.filter((d) => {
        if (d.deleted || d.creation_mode === 'template') {
            return false
        }
        const createdAt = new Date(d.created_at).getTime()
        return !Number.isNaN(createdAt) && createdAt >= cutoff
    })
    candidates.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
    const top = candidates[0]
    return top ? { id: top.id, name: top.name ?? null } : null
}

/**
 * Detects the dashboard the wizard was instructed to build, so completed-run surfaces can hand the
 * user straight to it. Fired by the Installation layer when a run (local or cloud) completes;
 * fetches once per (project, run start) and fails silent — the dashboard CTA is a bonus, never a
 * blocker.
 */
export const wizardDashboardLogic = kea<wizardDashboardLogicType>([
    path(['scenes', 'onboarding', 'wizardDashboardLogic']),
    connect(() => ({
        values: [projectLogic, ['currentProjectId']],
    })),
    loaders(({ values, cache }) => ({
        detectedDashboard: [
            null as DetectedDashboard | null,
            {
                detectWizardDashboard: async ({ startedAt }: { startedAt: string }, breakpoint) => {
                    const projectId = values.currentProjectId
                    if (projectId === null) {
                        return values.detectedDashboard
                    }
                    // One fetch per run: every surface that shows the completed state dispatches
                    // this, and re-listing dashboards for each of them buys nothing.
                    const attempted: Set<string> = (cache.attemptedRuns ??= new Set())
                    const key = `${projectId}:${startedAt}`
                    if (attempted.has(key)) {
                        return values.detectedDashboard
                    }
                    attempted.add(key)
                    try {
                        const page = await dashboardsList(String(projectId), { limit: DETECTION_PAGE_SIZE })
                        breakpoint()
                        return pickWizardDashboard(page.results ?? [], startedAt) ?? values.detectedDashboard
                    } catch {
                        // Detection is best-effort: a failed list just means no dashboard CTA.
                        return values.detectedDashboard
                    }
                },
            },
        ],
    })),
])

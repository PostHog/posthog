import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'

import { projectLogic } from 'scenes/projectLogic'

import { wizardSessionsList } from 'products/wizard/frontend/generated/api'
import type { WizardSessionDTOApi } from 'products/wizard/frontend/generated/api.schemas'

import type { wizardActiveSessionDetectorLogicType } from './wizardActiveSessionDetectorLogicType'

const WORKFLOW_ID = 'posthog-integration'

// A session counts as "active" if it was updated within this window and isn't
// already in a terminal phase. Same threshold the FAB uses for "is this still
// the user's current run" logic.
const ACTIVE_SESSION_THRESHOLD_MS = 10 * 60 * 1000

// Cheap REST repoll cadence used to surface a wizard run that was kicked off
// from outside the install step (e.g. user copied the command then navigated
// away to the dashboard before the CLI registered the session). The kea
// disposables plugin auto-pauses this while the tab is hidden, so an idle
// user reading mail isn't paying for it.
const REPOLL_INTERVAL_MS = 60 * 1000

// Grace window after a terminal phase before we let the SSE stream tear down.
// Gives the FAB time to show the completion / error UI before the connection
// drops.
const TERMINAL_GRACE_MS = 30 * 1000

function isSessionActive(session: WizardSessionDTOApi | null | undefined): boolean {
    if (!session) {
        return false
    }
    if (session.run_phase === 'completed' || session.run_phase === 'error') {
        return false
    }
    const updatedAt = new Date(session.updated_at).getTime()
    if (Number.isNaN(updatedAt)) {
        return false
    }
    return Date.now() - updatedAt < ACTIVE_SESSION_THRESHOLD_MS
}

/**
 * Decides whether the global wizard FAB should subscribe to the SSE stream.
 *
 * The FAB used to mount the streaming logic eagerly on every authenticated
 * page, which kept one pgbouncer slot pinned per logged-in user for the test
 * arm — see INC-886. This logic gates the stream behind a cheap REST poll so
 * the SSE only opens when we have evidence a wizard run is actually in flight.
 *
 * Sources of truth for `hasActiveSession`, in priority order:
 *  - `markActive()` from the install step's tracker logic, the moment the SSE
 *    sees a real session — flips the detector synchronously so the FAB
 *    survives a navigation away from the install step.
 *  - REST `wizardSessionsList(workflow_id=posthog-integration, limit=1)`,
 *    polled on mount, on tab visibility return, and on a 60s loop while the
 *    tab is visible.
 */
export const wizardActiveSessionDetectorLogic = kea<wizardActiveSessionDetectorLogicType>([
    path(['scenes', 'onboarding', 'wizardActiveSessionDetectorLogic']),
    connect(() => ({
        values: [projectLogic, ['currentProjectId']],
    })),
    actions({
        check: true,
        markActive: true,
        markInactive: true,
        scheduleMarkInactive: true,
        cancelScheduledMarkInactive: true,
    }),
    reducers({
        hasActiveSession: [
            false,
            {
                markActive: () => true,
                markInactive: () => false,
            },
        ],
    }),
    selectors({
        shouldStream: [(s) => [s.hasActiveSession], (hasActiveSession): boolean => hasActiveSession],
    }),
    listeners(({ actions, values, cache }) => ({
        check: async () => {
            const projectId = values.currentProjectId
            if (projectId === null) {
                return
            }
            try {
                const resp = await wizardSessionsList(String(projectId), {
                    workflow_id: WORKFLOW_ID,
                    limit: 1,
                })
                if (isSessionActive(resp.results[0])) {
                    actions.markActive()
                } else if (values.hasActiveSession) {
                    // Was streaming, REST now reports terminal / empty: defer
                    // teardown so any in-flight terminal UI gets its grace
                    // window via the same shared scheduler the tracker uses.
                    actions.scheduleMarkInactive()
                } else {
                    actions.markInactive()
                }
            } catch {
                // Transient REST failure — leave state as-is. If we were
                // streaming, the SSE-driven subscription on the tracker is
                // still the source of truth; if we weren't, we stay closed
                // and the next poll retries.
            }
        },
        markActive: () => {
            actions.cancelScheduledMarkInactive()
        },
        scheduleMarkInactive: () => {
            cache.disposables.add(() => {
                const id = window.setTimeout(() => actions.markInactive(), TERMINAL_GRACE_MS)
                return () => window.clearTimeout(id)
            }, 'mark-inactive-grace')
        },
        cancelScheduledMarkInactive: () => {
            cache.disposables.dispose('mark-inactive-grace')
        },
    })),
    afterMount(({ actions, cache }) => {
        // Disposables auto-pause/resume on visibilitychange, so a hidden tab
        // pays nothing and a tab returning to foreground re-runs setup —
        // which fires an immediate `check()` plus a fresh 60s interval.
        cache.disposables.add(() => {
            actions.check()
            const id = window.setInterval(() => actions.check(), REPOLL_INTERVAL_MS)
            return () => window.clearInterval(id)
        }, 'rest-poll')
    }),
])

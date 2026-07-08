import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { subscriptions } from 'kea-subscriptions'
import posthog from 'posthog-js'

import { ApiError } from 'lib/api-error'
import { projectLogic } from 'scenes/projectLogic'

// Cross-product import (onboarding core → wizard product) is intentional: this
// detector is the single client that owns the wizard latest-session poll. Going
// through the generated facade keeps types in sync with the backend serializer.
import { wizardSessionsLatestRetrieve } from 'products/wizard/frontend/generated/api'
import type { WizardSessionDTOApi } from 'products/wizard/frontend/generated/api.schemas'

import type { wizardActiveSessionDetectorLogicType } from './wizardActiveSessionDetectorLogicType'

const WORKFLOW_ID = 'posthog-integration'

// Cheap REST repoll cadence used to surface a wizard run that was kicked off
// from outside the install step (e.g. user copied the command then navigated
// away to the dashboard before the CLI registered the session). The kea
// disposables plugin auto-pauses this while the tab is hidden, so an idle
// user reading mail isn't paying for it.
const REPOLL_INTERVAL_MS = 60 * 1000

// Jitter window applied to the very first poll after mount, so a fleet-wide
// reload (deploy rollout, pgbouncer restart) doesn't synchronize the herd
// against the wizard latest-session endpoint.
const INITIAL_POLL_JITTER_MS = 30 * 1000

// Throttle for visibility-resume rechecks. The kea disposables plugin re-runs
// our setup on every `visibilitychange → visible`, which fires `check()` plus
// a fresh interval. Without throttling, rapid alt-tab flapping would translate
// into a burst of REST calls per tab per second.
const VISIBILITY_RESUME_THROTTLE_MS = 5 * 1000

// Grace window after a terminal phase before we let the SSE stream tear down.
// Gives the FAB time to show the completion / error UI before the connection
// drops.
const TERMINAL_GRACE_MS = 30 * 1000

// Hard upper bound on how long a single session keeps the FAB / SSE mounted,
// regardless of how often the CLI heartbeats `updated_at`. Protects against a
// wedged CLI publishing heartbeats forever, which would otherwise reproduce
// INC-886 at single-user scale.
const MAX_SESSION_LIFETIME_MS = 60 * 60 * 1000

export function isSessionActive(session: WizardSessionDTOApi | null | undefined): boolean {
    if (!session) {
        return false
    }
    if (session.run_phase === 'completed' || session.run_phase === 'error') {
        return false
    }
    // Server already computes staleness against the same 10-minute threshold
    // the FAB uses for "is this still the user's current run". Trusting the
    // server avoids a client-clock-skew failure mode where a forward-skewed
    // browser never sees the FAB.
    if (session.is_stale) {
        return false
    }
    const startedAt = new Date(session.started_at).getTime()
    if (!Number.isNaN(startedAt) && Date.now() - startedAt > MAX_SESSION_LIFETIME_MS) {
        return false
    }
    return true
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
 *  - REST `wizardSessionsLatestRetrieve(workflow_id=posthog-integration)`,
 *    polled on mount (jittered), on tab visibility return (throttled), and
 *    on a 60s loop while the tab is visible.
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
        setLastError: (error: string | null) => ({ error }),
        // Permanent kill — the backend told us we have no business calling this
        // endpoint (401/403 access denial). Set once and we stop polling for the
        // rest of the session lifetime.
        markPermanentlyDisabled: true,
    }),
    reducers({
        hasActiveSession: [
            false,
            {
                markActive: () => true,
                markInactive: () => false,
                markPermanentlyDisabled: () => false,
            },
        ],
        lastError: [
            null as string | null,
            {
                setLastError: (_, { error }) => error,
                markActive: () => null,
            },
        ],
        permanentlyDisabled: [
            false,
            {
                markPermanentlyDisabled: () => true,
            },
        ],
    }),
    selectors({
        shouldStream: [(s) => [s.hasActiveSession], (hasActiveSession): boolean => hasActiveSession],
    }),
    listeners(({ actions, values, cache }) => ({
        check: async () => {
            if (values.permanentlyDisabled) {
                return
            }
            const projectId = values.currentProjectId
            if (projectId === null) {
                return
            }
            // Concurrent-poll guard. The next-poll wins; older resolutions are
            // ignored — without this, an older "empty" can overwrite a newer
            // "active" if responses race.
            const seq = (cache.pollSeq = (cache.pollSeq ?? 0) + 1)
            try {
                // 204 (no run) returns an empty body, which the api client resolves to null.
                const session: WizardSessionDTOApi | null =
                    (await wizardSessionsLatestRetrieve(
                        String(projectId),
                        { workflow_id: WORKFLOW_ID },
                        { headers: { 'X-Wizard-Poll-Source': 'detector' } }
                    )) || null
                if (seq !== cache.pollSeq) {
                    return
                }
                if (isSessionActive(session)) {
                    actions.markActive()
                } else if (values.hasActiveSession) {
                    // Was streaming, REST now reports terminal / empty: defer
                    // teardown so any in-flight terminal UI gets its grace
                    // window via the same shared scheduler the tracker uses.
                    actions.scheduleMarkInactive()
                } else {
                    actions.markInactive()
                }
            } catch (err) {
                if (seq !== cache.pollSeq) {
                    return
                }
                // A cancelled fetch (unmount / navigation) is not a real failure;
                // skip it so it doesn't pollute lastError or telemetry.
                if (err instanceof Error && err.name === 'AbortError') {
                    return
                }
                if (err instanceof ApiError && err.status !== undefined) {
                    // 401/403 are structural access denials: the user can't or
                    // shouldn't talk to this endpoint. Stop polling permanently
                    // rather than burning load on a URL we know is wrong. A 404
                    // is deliberately excluded — during a rolling deploy the
                    // /latest/ route is absent on old pods, so a transient 404
                    // falls through to the retry path and self-heals once the
                    // rollout completes.
                    if (err.status === 401 || err.status === 403) {
                        posthog.captureException(err, {
                            tags: { feature: 'wizard-active-session-detector', reason: 'permanently_disabled' },
                            extra: { status: err.status },
                        })
                        actions.setLastError(
                            `wizard latest-session endpoint returned ${err.status} — disabling detector`
                        )
                        actions.markPermanentlyDisabled()
                        cache.disposables.dispose('rest-poll')
                        return
                    }
                }
                // Transient REST failure (including a deploy-window 404) — surface
                // it via lastError + Sentry, but leave hasActiveSession as-is so
                // SSE-driven state isn't clobbered. The next poll retries.
                posthog.captureException(err, {
                    tags: { feature: 'wizard-active-session-detector', reason: 'transient' },
                })
                actions.setLastError(err instanceof Error ? err.message : String(err))
            }
        },
        markActive: () => {
            actions.cancelScheduledMarkInactive()
        },
        markInactive: () => {
            cache.markInactiveAt = undefined
            cache.disposables.dispose('mark-inactive-grace')
        },
        scheduleMarkInactive: () => {
            // Idempotent: if a teardown timer is already scheduled, keep the
            // existing one rather than resetting the 30s clock. Without this,
            // repeated terminal SSE pings (or every 60s REST poll while the
            // terminal session is still in the active window) would push the
            // teardown out indefinitely — re-introducing the INC-886 pattern.
            if (cache.disposables.registry.has('mark-inactive-grace')) {
                return
            }
            // Deadline-based teardown. The disposables plugin re-runs this setup
            // on every `visibilitychange → visible`; pinning an absolute wall-
            // clock deadline (rather than a fresh TERMINAL_GRACE_MS timeout each
            // resume) means rapid alt-tabbing schedules only the *remaining*
            // time and can't starve teardown.
            cache.markInactiveAt = Date.now() + TERMINAL_GRACE_MS
            cache.disposables.add(() => {
                const remaining = Math.max(0, (cache.markInactiveAt ?? 0) - Date.now())
                const id = window.setTimeout(() => actions.markInactive(), remaining)
                return () => window.clearTimeout(id)
            }, 'mark-inactive-grace')
        },
        cancelScheduledMarkInactive: () => {
            cache.markInactiveAt = undefined
            cache.disposables.dispose('mark-inactive-grace')
        },
    })),
    subscriptions(({ actions, cache }) => ({
        // Project switching mid-session: drop any stale "active" state from the
        // previous project and force a fresh poll against the new project id.
        currentProjectId: (projectId: number | null, prev: number | null | undefined) => {
            if (projectId === prev) {
                return
            }
            // kea-subscriptions fires this once on mount with `prev === undefined`. Skip
            // that initial call so the jittered afterMount poll owns the first check —
            // otherwise every client polls immediately on a deploy reload, the exact
            // synchronized REST spike the jitter exists to spread out (INC-886).
            if (prev === undefined) {
                return
            }
            cache.disposables.dispose('mark-inactive-grace')
            actions.markInactive()
            if (projectId !== null) {
                actions.check()
            }
        },
    })),
    afterMount(({ actions, cache }) => {
        // Disposables auto-pause/resume on visibilitychange, so a hidden tab
        // pays nothing and a tab returning to foreground re-runs setup —
        // which, throttled, fires a `check()` plus a fresh 60s interval.
        cache.disposables.add(() => {
            // Stagger the initial call across the fleet so a deploy rollout
            // doesn't translate into a synchronized REST spike on the wizard
            // latest-session endpoint. Throttled by `cache.lastResumeAt` (the
            // instant of the previous setup run) so a rapid alt-tab can't bypass
            // the jitter via the disposables resume path.
            const now = Date.now()
            const sinceLastResume = now - (cache.lastResumeAt ?? 0)
            cache.lastResumeAt = now
            const initialDelay =
                sinceLastResume < VISIBILITY_RESUME_THROTTLE_MS
                    ? VISIBILITY_RESUME_THROTTLE_MS - sinceLastResume
                    : Math.random() * INITIAL_POLL_JITTER_MS
            const initialId = window.setTimeout(() => actions.check(), initialDelay)
            const intervalId = window.setInterval(() => actions.check(), REPOLL_INTERVAL_MS)
            return () => {
                window.clearTimeout(initialId)
                window.clearInterval(intervalId)
            }
        }, 'rest-poll')
    }),
])

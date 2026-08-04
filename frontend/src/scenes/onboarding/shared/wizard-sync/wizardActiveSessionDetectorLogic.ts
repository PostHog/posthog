import { MakeLogicType, actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { subscriptions } from 'kea-subscriptions'
import posthog from 'posthog-js'

import { ApiError } from 'lib/api-error'
import type { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { resolveOnboardingFlowVariant } from 'scenes/onboarding/onboardingVariants'
import { projectLogic } from 'scenes/projectLogic'
import { userLogic } from 'scenes/userLogic'

// Cross-product import (onboarding core → wizard product) is intentional: this
// detector is the single client that owns the wizard latest-session poll. Going
// through the generated facade keeps types in sync with the backend serializer.
import { wizardSessionsLatestRetrieve } from 'products/wizard/frontend/generated/api'
import type { WizardSessionDTOApi } from 'products/wizard/frontend/generated/api.schemas'

import { POSTHOG_INTEGRATION_WORKFLOW_ID, SELF_DRIVING_WORKFLOW_ID } from './workflows'

/** Always watched: the SDK install is what the app-wide FAB and nav button exist for. */
const WORKFLOW_ID = POSTHOG_INTEGRATION_WORKFLOW_ID

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

// After this many polls in a row fail, we stop withholding a verdict. Consumers that wait for one
// (the inbox takeover) would otherwise stay suppressed for the whole session on a degraded endpoint,
// with nothing in the UI to explain why. Failing open costs a wrong takeover during an outage;
// failing closed costs every new team its onboarding.
const MAX_CONSECUTIVE_POLL_FAILURES = 3

/**
 * Keep the detector mounted and watching a program until the returned cleanup runs. The one way to
 * hold a watch open, so the mount/watch pairing (and its teardown order: unwatch before unmount,
 * settling the refcount while the logic is still alive) can't be reassembled wrong at call sites.
 * The always-watched default program needs no registration, so it's skipped.
 */
export function watchWorkflowWhileMounted(workflowId: string): () => void {
    const unmount = wizardActiveSessionDetectorLogic.mount()
    const needsWatch = workflowId !== WORKFLOW_ID
    if (needsWatch) {
        wizardActiveSessionDetectorLogic.actions.watchWorkflow(workflowId)
    }
    return () => {
        if (needsWatch) {
            wizardActiveSessionDetectorLogic.actions.unwatchWorkflow(workflowId)
        }
        unmount()
    }
}

/**
 * Whether a run belongs to the person looking at it. The latest-session endpoint scopes by team and
 * program, not by user, so a teammate running the wizard would otherwise take over this browser's
 * single verdict slot: their run would tear down the viewer's widget, and their self-driving run
 * would suppress onboarding for someone who has no run at all. Runs from before attribution existed
 * carry no `created_by`, and those stay eligible rather than disappearing from the UI.
 */
function isOwnSession(session: WizardSessionDTOApi, userId: number | null): boolean {
    return !session.created_by || userId === null || session.created_by.id === userId
}

/** Sorts unparseable timestamps last rather than letting NaN scramble the comparison. */
function startedAtMs(session: WizardSessionDTOApi): number {
    const parsed = new Date(session.started_at).getTime()
    return Number.isNaN(parsed) ? -Infinity : parsed
}

export function isSessionActive(session: WizardSessionDTOApi | null | undefined): session is WizardSessionDTOApi {
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

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface wizardActiveSessionDetectorLogicValues {
    featureFlags: FeatureFlagsSet // featureFlagLogic
    currentProjectId: number | null // projectLogic
    activeWorkflowId: string | null
    consecutivePollFailures: number
    extraWorkflowCounts: Record<string, number>
    hasActiveSession: boolean
    hasResolvedSessionState: boolean
    lastError: string | null
    permanentlyDisabled: boolean
    shouldStream: boolean
    watchedWorkflows: string[]
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface wizardActiveSessionDetectorLogicActions {
    cancelScheduledMarkInactive: () => {
        value: true
    }
    check: () => {
        value: true
    }
    markActive: (workflowId: string) => {
        workflowId: string
    }
    markInactive: () => {
        value: true
    }
    markPermanentlyDisabled: () => {
        value: true
    }
    markResolutionUnavailable: () => {
        value: true
    }
    pollFailed: () => {
        value: true
    }
    resetSessionState: () => {
        value: true
    }
    scheduleMarkInactive: () => {
        value: true
    }
    setLastError: (error: string | null) => {
        error: string | null
    }
    unwatchWorkflow: (workflowId: string) => {
        workflowId: string
    }
    watchWorkflow: (workflowId: string) => {
        workflowId: string
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface wizardActiveSessionDetectorLogicMeta {
    __keaTypeGenInternalSelectorTypes: {
        hasActiveSession: (activeWorkflowId: string | null) => boolean
        watchedWorkflows: (extraWorkflowCounts: Record<string, number>, featureFlags: FeatureFlagsSet) => string[]
        shouldStream: (hasActiveSession: boolean) => boolean
    }
}

export type wizardActiveSessionDetectorLogicType = MakeLogicType<
    wizardActiveSessionDetectorLogicValues,
    wizardActiveSessionDetectorLogicActions,
    Record<string, any>,
    wizardActiveSessionDetectorLogicMeta
>

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
        values: [projectLogic, ['currentProjectId'], featureFlagLogic, ['featureFlags']],
    })),
    actions({
        check: true,
        // Surfaces register the wizard program they care about while mounted, so a user who never
        // enters the self-driving flow keeps paying for exactly one poll per tick.
        watchWorkflow: (workflowId: string) => ({ workflowId }),
        unwatchWorkflow: (workflowId: string) => ({ workflowId }),
        markActive: (workflowId: string) => ({ workflowId }),
        markInactive: true,
        // Back to "nobody knows" — for context changes (project switch) where the previous verdict
        // no longer describes anything. Distinct from markInactive, which is a verdict.
        resetSessionState: true,
        scheduleMarkInactive: true,
        cancelScheduledMarkInactive: true,
        setLastError: (error: string | null) => ({ error }),
        // Permanent kill — the backend told us we have no business calling this
        // endpoint (401/403 access denial). Set once and we stop polling for the
        // rest of the session lifetime.
        markPermanentlyDisabled: true,
        // Enough polls failed that we can't keep consumers waiting for a verdict. Unlike
        // markInactive this is not a claim about any run, so it leaves activeWorkflowId alone —
        // it only unblocks the surfaces gated on hasResolvedSessionState.
        markResolutionUnavailable: true,
        pollFailed: true,
    }),
    reducers({
        // Which program's run is live, so the FAB streams the one that is actually running rather
        // than assuming the SDK install.
        activeWorkflowId: [
            null as string | null,
            {
                markActive: (_, { workflowId }) => workflowId,
                markInactive: () => null,
                markPermanentlyDisabled: () => null,
                resetSessionState: () => null,
            },
        ],
        // Refcounted: several instances can watch the same program, and the last one out removes it.
        extraWorkflowCounts: [
            {} as Record<string, number>,
            {
                watchWorkflow: (state, { workflowId }) =>
                    workflowId === WORKFLOW_ID ? state : { ...state, [workflowId]: (state[workflowId] ?? 0) + 1 },
                unwatchWorkflow: (state, { workflowId }) => {
                    const next = (state[workflowId] ?? 0) - 1
                    if (next > 0) {
                        return { ...state, [workflowId]: next }
                    }
                    const { [workflowId]: _dropped, ...rest } = state
                    return rest
                },
            },
        ],
        // Whether the detector has ever reached a verdict (a poll settled, a stream reported in, or
        // polling was killed outright). `activeWorkflowId === null` is ambiguous on its own: it also
        // covers "nobody has asked yet", and the two need different treatment — a consumer that
        // must not act on a wrong "not running" (the inbox takeover) waits for this instead.
        hasResolvedSessionState: [
            false,
            {
                markActive: () => true,
                markInactive: () => true,
                scheduleMarkInactive: () => true,
                // Access denial means there will never be a verdict; "resolved, not running" is the
                // only answer consumers can act on.
                markPermanentlyDisabled: () => true,
                markResolutionUnavailable: () => true,
                // A verdict about the previous project says nothing about the new one.
                resetSessionState: () => false,
            },
        ],
        // Consecutive failed polls, so a persistently broken endpoint eventually stops withholding
        // a verdict. Any settled poll clears it.
        consecutivePollFailures: [
            0,
            {
                markActive: () => 0,
                markInactive: () => 0,
                scheduleMarkInactive: () => 0,
                resetSessionState: () => 0,
                pollFailed: (state: number) => state + 1,
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
        hasActiveSession: [
            (s) => [s.activeWorkflowId],
            (activeWorkflowId: string | null): boolean => activeWorkflowId !== null,
        ],
        watchedWorkflows: [
            (s) => [s.extraWorkflowCounts, s.featureFlags],
            (extraWorkflowCounts: Record<string, number>, featureFlags: FeatureFlagsSet): string[] => {
                // Self-driving users are watched from the start, not only once an install-progress
                // instance registers: otherwise reloading any page mid-run loses the widget, because
                // nothing would be polling the program that is actually running.
                const base =
                    resolveOnboardingFlowVariant(featureFlags) === 'self-driving'
                        ? [WORKFLOW_ID, SELF_DRIVING_WORKFLOW_ID]
                        : [WORKFLOW_ID]
                return [...new Set([...base, ...Object.keys(extraWorkflowCounts)])]
            },
        ],
        shouldStream: [(s) => [s.hasActiveSession], (hasActiveSession: boolean): boolean => hasActiveSession],
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
            // Settled rather than all-or-nothing: one program's failure must not discard another's
            // successful answer, or a flaky response for the SDK install would hide a self-driving
            // run the server reported correctly.
            const results = await Promise.allSettled(
                values.watchedWorkflows.map(
                    async (workflowId): Promise<WizardSessionDTOApi | null> =>
                        // 204 (no run) returns an empty body, which the api client resolves to null.
                        (await wizardSessionsLatestRetrieve(
                            String(projectId),
                            { workflow_id: workflowId },
                            { headers: { 'X-Wizard-Poll-Source': 'detector' } }
                        )) || null
                )
            )
            if (seq !== cache.pollSeq) {
                return
            }

            const sessions: (WizardSessionDTOApi | null)[] = []
            const errors: unknown[] = []
            for (const result of results) {
                if (result.status === 'fulfilled') {
                    sessions.push(result.value)
                } else {
                    errors.push(result.reason)
                }
            }

            // A cancelled fetch (unmount / navigation) is not a real failure; skip the whole poll so
            // it doesn't pollute lastError or telemetry.
            if (errors.some((err) => err instanceof Error && err.name === 'AbortError')) {
                return
            }

            // 401/403 are structural access denials: the user can't or shouldn't talk to this
            // endpoint. Stop polling permanently rather than burning load on a URL we know is wrong
            // — but only when every program agrees, so one program's denial can't silence a healthy
            // one. A 404 is deliberately excluded: during a rolling deploy the /latest/ route is
            // absent on old pods, so a transient 404 falls through to the retry path and self-heals.
            const denials = errors.filter(
                (err) => err instanceof ApiError && (err.status === 401 || err.status === 403)
            )
            if (denials.length > 0 && denials.length === results.length) {
                const denial = denials[0] as ApiError
                posthog.captureException(denial, {
                    tags: { feature: 'wizard-active-session-detector', reason: 'permanently_disabled' },
                    extra: { status: denial.status },
                })
                actions.setLastError(`wizard latest-session endpoint returned ${denial.status} — disabling detector`)
                actions.markPermanentlyDisabled()
                cache.disposables.dispose('rest-poll')
                return
            }

            for (const err of errors) {
                // Transient REST failure (including a deploy-window 404) — surface it via
                // lastError + Sentry. The next poll retries.
                posthog.captureException(err, {
                    tags: { feature: 'wizard-active-session-detector', reason: 'transient' },
                })
            }
            if (errors.length > 0) {
                actions.setLastError(errors[0] instanceof Error ? (errors[0] as Error).message : String(errors[0]))
            }

            // Newest wins when two programs both look live — a user who kicked off self-driving
            // after an SDK install should see the run they just started. Parsed rather than compared
            // as strings: the CLI mints these timestamps, so offset and fractional-second precision
            // aren't guaranteed to be uniform, and lexicographic order would rank them wrong.
            // Read rather than connected: `userLogic` loads the user on mount, and this detector runs
            // app-wide, so connecting it would pull that fetch into every surface that mounts us. In
            // the app it is always already mounted; if it somehow isn't, no id means no filtering.
            const userId = userLogic.findMounted()?.values.user?.id ?? null
            const live = sessions
                .filter(isSessionActive)
                .filter((session) => isOwnSession(session, userId))
                .sort((a, b) => startedAtMs(b) - startedAtMs(a))[0]
            if (live) {
                actions.markActive(live.workflow_id)
                return
            }

            if (errors.length > 0) {
                // "Nothing live" is only a verdict when every program answered. A failure on the
                // program that is actually running, alongside an empty answer from the other, looks
                // identical to "no run" from here — and tearing down over that would kill a live
                // run's widget. Leave the state alone and count the failure toward giving up on a
                // verdict, so consumers waiting on one aren't stranded either.
                actions.pollFailed()
                if (values.consecutivePollFailures >= MAX_CONSECUTIVE_POLL_FAILURES) {
                    actions.markResolutionUnavailable()
                }
                return
            }

            if (values.hasActiveSession) {
                // Was streaming, REST now reports terminal / empty: defer
                // teardown so any in-flight terminal UI gets its grace
                // window via the same shared scheduler the tracker uses.
                actions.scheduleMarkInactive()
            } else {
                actions.markInactive()
            }
        },
        markActive: () => {
            actions.cancelScheduledMarkInactive()
        },
        markInactive: () => {
            cache.markInactiveAt = undefined
            cache.disposables.dispose('mark-inactive-grace')
        },
        resetSessionState: () => {
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
    subscriptions(({ actions }) => ({
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
            actions.resetSessionState()
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

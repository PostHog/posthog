import { actions, afterMount, beforeUnmount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { subscriptions } from 'kea-subscriptions'

import { elapsedSecondsFrom } from 'lib/utils/datetime'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

import type { WizardSessionDTOApi } from 'products/wizard/frontend/generated/api.schemas'
import { wizardSessionStreamLogic } from 'products/wizard/frontend/wizardSessionStreamLogic'

import {
    isSessionActive,
    wizardActiveSessionDetectorLogic,
} from '../../../shared/wizard-sync/wizardActiveSessionDetectorLogic'
import type { wizardProgressTrackerLogicType } from './wizardProgressTrackerLogicType'

export type DisplayState =
    | 'preTakeover' // No session yet — keep the command card visible.
    | 'connecting' // Session exists but transport is reconnecting.
    | 'running' // run_phase === 'running'
    | 'completed' // run_phase === 'completed'
    | 'error' // run_phase === 'error'

export interface ActivityEntry {
    /** Wall-clock timestamp (ms epoch) used for the visible HH:MM:SS prefix. */
    at: number
    /** Pre-formatted line: terse, lowercase, terminal-tail style. */
    text: string
}

const MAX_ACTIVITY_ENTRIES = 50
const TICK_INTERVAL_MS = 1_000
const HEARTBEAT_INTERVAL_MS = 30_000
const HEARTBEAT_QUIET_THRESHOLD_MS = 25_000

// A session counts as "current" if it was updated within the last 10 minutes.
// Lets the FAB ignore stale terminal sessions left over from previous runs / test
// data when a user lands on the app, while still re-surfacing recently-completed
// runs after a quick navigation away and back.
const SESSION_CURRENT_THRESHOLD_MS = 10 * 60 * 1000

const WORKFLOW_ID = 'posthog-integration'

// Per-session telemetry guards, deliberately module-scoped rather than on the kea
// `cache`. The tracker logic unmounts whenever the FAB's `shouldStream` flips false
// and the install step isn't mounted, and a remount wipes `cache` — so a cache-based
// guard would let the SSE redeliver a still-in-flight session and re-fire these
// events. Keying by session_id at module scope makes "once per session" hold across
// remounts for the whole page load. (A hard reload starts a fresh page session; the
// reach funnel is read on unique users, so that boundary is acceptable.)
const reportedDetectedSessions = new Set<string>()
const reportedFinishedSessions = new Set<string>()
const reportedDismissedSessions = new Set<string>()

// Test-only: clear the module-level guards so each case starts from a clean slate.
export function resetWizardSyncTelemetryForTests(): void {
    reportedDetectedSessions.clear()
    reportedFinishedSessions.clear()
    reportedDismissedSessions.clear()
}

function runPhaseMessage(phase: string): string {
    if (phase === 'completed') {
        return 'wizard finished'
    }
    if (phase === 'error') {
        return 'wizard hit an error'
    }
    if (phase === 'running') {
        return 'wizard started running'
    }
    return `wizard phase: ${phase}`
}

function taskStatusVerb(status: string): string {
    switch (status) {
        case 'in_progress':
            return 'started:'
        case 'completed':
            return 'done:'
        case 'failed':
            return 'failed:'
        case 'canceled':
            return 'skipped:'
        case 'pending':
            return 'queued:'
        default:
            return `${status}:`
    }
}

/**
 * Drives the wizard takeover panel:
 *   - subscribes to wizardSessionStreamLogic for live session state
 *   - keeps a synthetic activity log (tail -f vibe) so the panel never goes silent
 *   - ticks a 1Hz running-time counter
 *   - emits a "still working…" heartbeat when the log goes quiet during a run
 *   - exposes a derived DisplayState that the panel switches on
 */
export const wizardProgressTrackerLogic = kea<wizardProgressTrackerLogicType>([
    path(['scenes', 'onboarding', 'wizardProgressTrackerLogic']),
    connect(() => ({
        values: [
            wizardSessionStreamLogic({ workflowId: WORKFLOW_ID }),
            ['latestSession', 'connectionStatus', 'lastError'],
        ],
        actions: [
            wizardSessionStreamLogic({ workflowId: WORKFLOW_ID }),
            ['connect', 'disconnect'],
            wizardActiveSessionDetectorLogic,
            ['markActive', 'scheduleMarkInactive'],
            eventUsageLogic,
            ['reportWizardSyncSessionDetected', 'reportWizardSyncSessionFinished', 'reportWizardSyncDismissed'],
        ],
    })),
    actions({
        appendActivity: (text: string) => ({ text, at: Date.now() }),
        tick: (now: number) => ({ now }),
        taskStarted: (taskId: string, at: number) => ({ taskId, at }),
        // User-initiated dismiss of the floating FAB once a run has reached a terminal phase.
        dismiss: true,
        // Set by the install-step confirmation card on mount/unmount. While true, the FAB
        // hides — so the inline acknowledgement and the floating widget never overlap.
        setPanelMounted: (mounted: boolean) => ({ mounted }),
        // Sticky flag — set the first time we observe a session that's recent enough to
        // count as live. Old terminal sessions sitting in the DB stay invisible.
        markSessionCurrent: true,
    }),
    reducers({
        activityLog: [
            [] as ActivityEntry[],
            {
                appendActivity: (state, { text, at }) => {
                    const next = [...state, { text, at }]
                    return next.length > MAX_ACTIVITY_ENTRIES ? next.slice(next.length - MAX_ACTIVITY_ENTRIES) : next
                },
            },
        ],
        now: [
            Date.now(),
            {
                tick: (_, { now }) => now,
            },
        ],
        // Wall-clock timestamp (ms) of the moment each task was observed entering `in_progress`.
        // Used to render a per-task running timer. Last write wins so retries restart the clock.
        taskStartedAt: [
            {} as Record<string, number>,
            {
                taskStarted: (state, { taskId, at }) => ({ ...state, [taskId]: at }),
            },
        ],
        dismissed: [
            false,
            {
                dismiss: () => true,
            },
        ],
        panelMounted: [
            false,
            {
                setPanelMounted: (_, { mounted }) => mounted,
            },
        ],
        sessionIsCurrent: [
            false,
            {
                markSessionCurrent: () => true,
            },
        ],
    }),
    selectors({
        displayState: [
            (s) => [s.latestSession, s.connectionStatus],
            (latestSession, connectionStatus): DisplayState => {
                if (!latestSession) {
                    return 'preTakeover'
                }
                // Terminal run_phase states are sticky — the wizard CLI closes the SSE
                // connection cleanly after `completed`/`error`, which would otherwise
                // flip the panel back to a transient "reconnecting…" state right when
                // the user is supposed to see the completion screen.
                const phase = latestSession.run_phase
                if (phase === 'completed') {
                    return 'completed'
                }
                if (phase === 'error') {
                    return 'error'
                }
                if (connectionStatus === 'connecting' || connectionStatus === 'error') {
                    return 'connecting'
                }
                return 'running'
            },
        ],
        elapsedSeconds: [
            (s) => [s.latestSession, s.now],
            (latestSession, now): number => (latestSession ? elapsedSecondsFrom(latestSession.started_at, now) : 0),
        ],
    }),
    subscriptions(({ actions }) => ({
        connectionStatus: (status, prev) => {
            if (status === prev) {
                return
            }
            const messages: Record<string, string> = {
                connecting: 'connecting…',
                open: 'connected, waiting for wizard',
                closed: 'stream closed',
                error: 'connection error — reconnecting…',
                idle: '',
            }
            const text = messages[status as string]
            if (text) {
                actions.appendActivity(text)
            }
        },
        latestSession: (session: WizardSessionDTOApi | null, prev: WizardSessionDTOApi | null) => {
            if (!session) {
                return
            }
            const now = Date.now()
            const updatedAt = new Date(session.updated_at).getTime()
            const isFresh = !Number.isNaN(updatedAt) && now - updatedAt < SESSION_CURRENT_THRESHOLD_MS
            if (isFresh) {
                actions.markSessionCurrent()
                // Reach metric: count each live wizard session the sync surfaces, once per
                // session_id. Gated on freshness so stale terminal rows sitting in the DB —
                // which never reach the user — don't inflate the funnel.
                if (!reportedDetectedSessions.has(session.session_id)) {
                    reportedDetectedSessions.add(session.session_id)
                    actions.reportWizardSyncSessionDetected({
                        workflowId: WORKFLOW_ID,
                        skillId: session.skill_id,
                        runPhase: session.run_phase,
                        taskCount: session.tasks.length,
                    })
                }
            }
            // Keep the global detector in sync so the FAB survives a navigation
            // away from the install step. Gate on the detector's shared
            // eligibility predicate (server staleness + lifetime cap + terminal
            // phase) so the SSE and REST paths agree on when streaming may
            // continue — a wedged CLI heartbeating `updated_at` past the lifetime
            // cap stops re-arming markActive, letting teardown actually run. Only
            // schedule teardown on the eligible → ineligible *transition* so
            // repeated re-polls don't reset the clock (the detector's
            // `scheduleMarkInactive` is also idempotent as a belt-and-braces guard).
            const eligible = isSessionActive(session)
            const wasEligible = isSessionActive(prev)
            if (eligible) {
                actions.markActive()
            } else if (wasEligible) {
                actions.scheduleMarkInactive()
            }
            if (!prev) {
                actions.appendActivity(`session started for ${session.skill_id}`)
                // Tasks we joined mid-run: best-effort, start the per-task clock now.
                for (const task of session.tasks) {
                    if (task.status === 'in_progress') {
                        actions.taskStarted(task.id, now)
                    }
                }
                return
            }
            if (session.run_phase !== prev.run_phase) {
                actions.appendActivity(runPhaseMessage(session.run_phase))
                const isTerminal = session.run_phase === 'completed' || session.run_phase === 'error'
                // Outcome metric: fire once when a run the user watched live reaches a
                // terminal phase. Terminal phases are sticky, so this transition is observed
                // at most once per session — the id guard covers any SSE redelivery.
                if (isTerminal && !reportedFinishedSessions.has(session.session_id)) {
                    reportedFinishedSessions.add(session.session_id)
                    actions.reportWizardSyncSessionFinished({
                        workflowId: WORKFLOW_ID,
                        skillId: session.skill_id,
                        outcome: session.run_phase,
                        taskCount: session.tasks.length,
                        completedTaskCount: session.tasks.filter((t) => t.status === 'completed').length,
                        elapsedSeconds: elapsedSecondsFrom(session.started_at, now),
                    })
                }
            }
            const prevTaskKeys = new Set(prev.tasks.map((t) => `${t.id}::${t.status}`))
            for (const task of session.tasks) {
                const key = `${task.id}::${task.status}`
                if (!prevTaskKeys.has(key)) {
                    actions.appendActivity(`${taskStatusVerb(task.status)} ${task.title}`)
                    if (task.status === 'in_progress') {
                        actions.taskStarted(task.id, now)
                    }
                }
            }
        },
    })),
    listeners(({ values, actions }) => ({
        dismiss: () => {
            const sessionId = values.latestSession?.session_id
            // No session means nothing to attribute the dismissal to, and without a
            // session_id the once-per-session guard can't hold — bail rather than fire
            // an unguarded event on every dispatch.
            if (!sessionId) {
                return
            }
            // Guard against a double-click landing two `dismiss` dispatches before the
            // FAB re-renders itself away: capture at most once per session.
            if (reportedDismissedSessions.has(sessionId)) {
                return
            }
            reportedDismissedSessions.add(sessionId)
            actions.reportWizardSyncDismissed({
                workflowId: WORKFLOW_ID,
                skillId: values.latestSession?.skill_id,
                outcome: values.displayState,
                elapsedSeconds: values.elapsedSeconds,
            })
        },
    })),
    afterMount(({ actions, cache, values }) => {
        actions.connect()
        actions.appendActivity('opening wizard session stream…')
        cache.disposables.add(() => {
            const id = window.setInterval(() => actions.tick(Date.now()), TICK_INTERVAL_MS)
            return () => window.clearInterval(id)
        }, 'tick')
        cache.disposables.add(() => {
            const id = window.setInterval(() => {
                // The kea-disposables plugin pauses timers when the tab is hidden and
                // re-creates them on resume. That re-created interval can fire during a
                // window where the connected wizardSessionStreamLogic has been torn down
                // (e.g. the FAB unmounting after a feature-flag re-evaluation). Reading a
                // value off an unmounted logic throws
                // `[KEA] Can not find path "...wizardSessionStreamLogic..." in the store.`,
                // so bail out unless the stream logic is currently mounted.
                if (!wizardSessionStreamLogic.findMounted({ workflowId: WORKFLOW_ID })) {
                    return
                }
                // Heartbeat: if the log has gone quiet for HEARTBEAT_QUIET_THRESHOLD_MS
                // while the wizard is still running, append a "still working" line so
                // the panel never looks frozen.
                const session = values.latestSession
                if (!session || session.run_phase !== 'running') {
                    return
                }
                const log = values.activityLog
                const latest = log.length > 0 ? log[log.length - 1] : null
                const quietFor = latest ? Date.now() - latest.at : Infinity
                if (quietFor >= HEARTBEAT_QUIET_THRESHOLD_MS) {
                    actions.appendActivity('still working…')
                }
            }, HEARTBEAT_INTERVAL_MS)
            return () => window.clearInterval(id)
        }, 'heartbeat')
    }),
    beforeUnmount(({ actions }) => {
        actions.disconnect()
    }),
])

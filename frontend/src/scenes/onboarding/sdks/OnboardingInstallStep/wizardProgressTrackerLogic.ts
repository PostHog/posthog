import { actions, afterMount, beforeUnmount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { subscriptions } from 'kea-subscriptions'

import type { WizardSessionApi } from 'products/wizard/frontend/generated/api.schemas'
import { wizardSessionStreamLogic } from 'products/wizard/frontend/wizardSessionStreamLogic'

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

const WORKFLOW_ID = 'posthog-integration'

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
        actions: [wizardSessionStreamLogic({ workflowId: WORKFLOW_ID }), ['connect', 'disconnect']],
    })),
    actions({
        appendActivity: (text: string) => ({ text, at: Date.now() }),
        tick: (now: number) => ({ now }),
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
    }),
    selectors({
        displayState: [
            (s) => [s.latestSession, s.connectionStatus],
            (latestSession, connectionStatus): DisplayState => {
                if (!latestSession) {
                    return 'preTakeover'
                }
                if (connectionStatus === 'connecting' || connectionStatus === 'error') {
                    return 'connecting'
                }
                const phase = latestSession.run_phase
                if (phase === 'completed') {
                    return 'completed'
                }
                if (phase === 'error') {
                    return 'error'
                }
                return 'running'
            },
        ],
        elapsedSeconds: [
            (s) => [s.latestSession, s.now],
            (latestSession, now): number => {
                if (!latestSession) {
                    return 0
                }
                const startedAt = new Date(latestSession.started_at).getTime()
                if (Number.isNaN(startedAt)) {
                    return 0
                }
                return Math.max(0, Math.floor((now - startedAt) / 1000))
            },
        ],
    }),
    listeners(() => ({
        // No imperative listeners; reducers + subscriptions cover state changes.
    })),
    subscriptions(({ actions }) => ({
        connectionStatus: (status, prev) => {
            if (status === prev) {
                return
            }
            const messages: Record<string, string> = {
                connecting: 'connecting…',
                open: 'connected, waiting for wizard',
                closed: 'stream closed',
                error: 'transport error — reconnecting…',
                idle: '',
            }
            const text = messages[status as string]
            if (text) {
                actions.appendActivity(text)
            }
        },
        latestSession: (session: WizardSessionApi | null, prev: WizardSessionApi | null) => {
            if (!session) {
                return
            }
            if (!prev) {
                actions.appendActivity(`session started · ${session.workflow_id} · ${session.skill_id}`)
                return
            }
            if (session.run_phase !== prev.run_phase) {
                actions.appendActivity(`run phase → ${session.run_phase}`)
            }
            const prevTaskKeys = new Set(prev.tasks.map((t) => `${t.id}::${t.status}`))
            for (const task of session.tasks) {
                const key = `${task.id}::${task.status}`
                if (!prevTaskKeys.has(key)) {
                    actions.appendActivity(`${task.status}: ${task.title}`)
                }
            }
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

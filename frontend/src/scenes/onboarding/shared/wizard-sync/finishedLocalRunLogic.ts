import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'

import { projectLogic } from 'scenes/projectLogic'

import type { WizardSessionDTOApi } from 'products/wizard/frontend/generated/api.schemas'

import type { finishedLocalRunLogicType } from './finishedLocalRunLogicType'
import { wizardDashboardLogic } from './wizardDashboardLogic'

/** A terminal local wizard run, snapshotted so its handoff outlives the session stream. */
export interface FinishedLocalRunHandle {
    sessionId: string
    /** Project the run belongs to — the handle lives in localStorage, shared across accounts. */
    projectId: number
    startedAt: string
    finishedAt: string
    runPhase: 'completed' | 'error'
    tasks: { id: string; title: string; status: string }[]
    error: { message?: string } | null
}

/**
 * Keeps a finished local wizard run on screen until the user dismisses it. The live session stream
 * gates itself off shortly after a run goes terminal (INC-886), which used to take the FAB down with
 * it — dismissing the handoff surface is the user's call, not a timer's. Written by the Installation
 * layer's local bookkeeping the moment a watched run turns terminal; persisted so a reload doesn't
 * eat the handoff; superseded silently when a new local run starts.
 */
export const finishedLocalRunLogic = kea<finishedLocalRunLogicType>([
    path(['scenes', 'onboarding', 'finishedLocalRunLogic']),
    connect(() => ({
        values: [projectLogic, ['currentProjectId']],
        actions: [wizardDashboardLogic, ['detectWizardDashboard']],
    })),
    actions({
        recordFinishedLocalRun: (session: WizardSessionDTOApi) => ({ session }),
        setFinishedLocalRun: (handle: FinishedLocalRunHandle) => ({ handle }),
        // A different local run went live — the previous run's handoff is superseded, not dismissed
        // (no telemetry; mirrors setActiveCloudRun overwriting the previous cloud handle).
        supersedeFinishedLocalRun: (sessionId: string) => ({ sessionId }),
        // The user's explicit dismissal — the only path that removes a finished run without a
        // replacement. Remembered so an SSE redelivery of the same terminal session can't resurrect
        // the surface.
        dismissLocalRun: (sessionId: string) => ({ sessionId }),
    }),
    reducers({
        persistedFinishedLocalRun: [
            null as FinishedLocalRunHandle | null,
            { persist: true },
            {
                setFinishedLocalRun: (_, { handle }) => handle,
                supersedeFinishedLocalRun: (state, { sessionId }) =>
                    state && state.sessionId !== sessionId ? null : state,
                dismissLocalRun: (state, { sessionId }) => (state?.sessionId === sessionId ? null : state),
            },
        ],
        dismissedSessionId: [
            null as string | null,
            { persist: true },
            {
                dismissLocalRun: (_, { sessionId }) => sessionId,
            },
        ],
    }),
    selectors({
        finishedLocalRun: [
            (s) => [s.persistedFinishedLocalRun, s.currentProjectId],
            (persistedFinishedLocalRun, currentProjectId): FinishedLocalRunHandle | null =>
                persistedFinishedLocalRun && persistedFinishedLocalRun.projectId === currentProjectId
                    ? persistedFinishedLocalRun
                    : null,
        ],
    }),
    listeners(({ actions, values }) => ({
        recordFinishedLocalRun: ({ session }) => {
            const isTerminal = session.run_phase === 'completed' || session.run_phase === 'error'
            if (!isTerminal || session.session_id === values.dismissedSessionId) {
                return
            }
            const projectId = values.currentProjectId
            if (projectId === null) {
                return
            }
            actions.setFinishedLocalRun({
                sessionId: session.session_id,
                projectId,
                startedAt: session.started_at,
                finishedAt: session.updated_at,
                runPhase: session.run_phase === 'error' ? 'error' : 'completed',
                tasks: (session.tasks ?? []).map((t) => ({ id: t.id, title: t.title, status: t.status })),
                error: (session.error as { message?: string } | null) ?? null,
            })
            if (session.run_phase === 'completed') {
                actions.detectWizardDashboard({ startedAt: session.started_at })
            }
        },
    })),
    afterMount(({ actions, values }) => {
        // A completed handle restored from a previous pageload still deserves its dashboard CTA.
        const handle = values.finishedLocalRun
        if (handle?.runPhase === 'completed') {
            actions.detectWizardDashboard({ startedAt: handle.startedAt })
        }
    }),
])

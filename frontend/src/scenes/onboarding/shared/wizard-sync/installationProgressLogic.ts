import {
    MakeLogicType,
    actions,
    afterMount,
    beforeUnmount,
    connect,
    kea,
    key,
    listeners,
    path,
    props,
    reducers,
    selectors,
} from 'kea'

import { elapsedSecondsFrom } from 'lib/utils/datetime'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

import type { WizardSessionDTOApi } from 'products/wizard/frontend/generated/api.schemas'
import { wizardSessionStreamLogic } from 'products/wizard/frontend/wizardSessionStreamLogic'

import type { WizardConnectionStatus } from '../../../../../../products/wizard/frontend/wizardSessionStreamLogic'
import { activeCloudRunLogic } from './activeCloudRunLogic'
import type { CloudRunHandle } from './activeCloudRunLogic'
import { finishedLocalRunLogic } from './finishedLocalRunLogic'
import { cloudProgress, isSessionFresh, localProgress } from './installationProgress'
import { taskRunStreamLogic, TaskRunProgressStep, TaskRunStreamState } from './taskRunStreamLogic'
import type { TaskRunConnectionStatus } from './taskRunStreamLogic'
import {
    isSessionActive,
    watchWorkflowWhileMounted,
    wizardActiveSessionDetectorLogic,
} from './wizardActiveSessionDetectorLogic'
import { wizardSyncUiLogic } from './wizardSyncUiLogic'
import { resolveWorkflowId } from './workflows'

// Per-session telemetry guards, deliberately module-scoped rather than on the kea `cache`: the logic
// unmounts whenever its last consumer does (FAB gate flips, install step navigated away), and a
// remount wipes `cache` — so a cache-based guard would let the SSE redeliver a still-in-flight
// session and re-fire these events. Keying by session_id at module scope makes "once per session"
// hold across remounts for the whole page load.
const reportedDetectedSessions = new Set<string>()
const reportedFinishedSessions = new Set<string>()

// One "share" of the wizard session transport per mounted instance. wizardSessionStreamLogic
// connect/disconnect is NOT refcounted and the keyed instance is shared across instances of this
// logic, so nobody may cut the transport out from under a co-mounted consumer: shares are released
// on unmount (and early, by a cloud instance whose run went terminal), and only the LAST release
// disconnects. Without this, a finishing cloud run would kill the stream for the still-mounted
// local instance and the "Run it yourself" recovery flow would go deaf until a full remount.
// Keyed by stream, not global: `wizardSessionStreamLogic` is itself keyed per workflow, so a single
// flat set would both collide (two workflows share the instance key `local`) and leak (the last
// release of ANY workflow would disconnect only its own stream, stranding the others).
const sessionStreamShares = new Map<string, Set<string>>()

function releaseSessionShare(streamKey: string, shareKey: string, disconnectSession: () => void): void {
    const shares = sessionStreamShares.get(streamKey)
    if (!shares?.delete(shareKey)) {
        return
    }
    if (shares.size === 0) {
        sessionStreamShares.delete(streamKey)
        disconnectSession()
    }
}

function acquireSessionShare(streamKey: string, shareKey: string): void {
    const shares = sessionStreamShares.get(streamKey) ?? new Set<string>()
    shares.add(shareKey)
    sessionStreamShares.set(streamKey, shares)
}

export function resetWizardSyncTelemetryForTests(): void {
    reportedDetectedSessions.clear()
    reportedFinishedSessions.clear()
    sessionStreamShares.clear()
}

/**
 * Identity of one mounted instance. Shared by `key()` and the stream-share bookkeeping, which must
 * agree — if they drift, the refcount releases a share nobody holds and the transport leaks.
 */
function instanceKey(props: InstallationProgressLogicProps): string {
    const mode = props.mode === 'cloud' ? `cloud:${props.runId ?? ''}` : 'local'
    return `${resolveWorkflowId(props.workflowId)}:${mode}`
}

/**
 * The `wizardSessionStreamLogic` instance an install-progress instance shares. Mirrors that logic's
 * own key. `skillId` is deliberately left unset: the CLI reassigns `session.skillId` per agent run,
 * so a self-driving run's skill flips to the framework name mid-session and a skill-scoped
 * subscription would drop out partway through.
 */
function sessionStreamKey(props: InstallationProgressLogicProps): string {
    return `${resolveWorkflowId(props.workflowId)}::*`
}

export type InstallationMode = 'local' | 'cloud'
export type InstallationPhase = 'idle' | 'connecting' | 'running' | 'completed' | 'error'
export type InstallationStepStatus = 'pending' | 'in_progress' | 'completed' | 'failed'

export interface InstallationStep {
    id: string
    label: string
    status: InstallationStepStatus
    detail: string | null
    /** Set on steps reported by the wizard itself (session tasks), as opposed to the run pipeline —
     * the timeline renders them nested under the pipeline's wizard stage. */
    source?: 'wizard'
}

/** The wizard's in-flight `wizard_ask` prompt, published on the session row while the CLI is
 * blocked on the user. Sensitive asks (secrets) carry no prompt text by design. */
export interface WizardPendingInput {
    id: string
    askedAt: string
    questionCount: number
    sensitive: boolean
    prompts: string[]
}

export interface InstallationProgress {
    phase: InstallationPhase
    steps: InstallationStep[]
    error: { title: string; detail: string | null } | null
    prUrl: string | null
    /** The bound PR was merged (webhook-recorded on the run's output). */
    prMerged: boolean
    isCurrent: boolean
    /** Set while the wizard is waiting on the user in the terminal — the widget's attention state.
     * Cleared by the next session push without the field (answered, cancelled, or timed out). */
    pendingInput: WizardPendingInput | null
    /** Who started the run (null when unknown). `email` is for the "is this me?" check. */
    startedBy: { name: string; email: string } | null
    /** Markdown handoff doc the wizard produced (its setup report), once the run has one. Sticky on
     * the session row, so it survives later pushes and the finished-run snapshot. */
    handoffText: string | null
}

export interface InstallationProgressLogicProps {
    mode: InstallationMode
    runId?: string
    taskId?: string
    /** Wizard program to track. Defaults to the SDK install (`posthog-integration`). */
    workflowId?: string
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface installationProgressLogicValues {
    activeCloudRun: CloudRunHandle | null // activeCloudRunLogic
    dismissedSessionId: string | null // finishedLocalRunLogic
    isStalled: boolean // taskRunStreamLogic
    lastActivityAt: number | null // taskRunStreamLogic
    progressSteps: TaskRunProgressStep[] // taskRunStreamLogic
    taskConnectionStatus: TaskRunConnectionStatus // taskRunStreamLogic
    taskRunState: TaskRunStreamState | null // taskRunStreamLogic
    latestSession: WizardSessionDTOApi | null // wizardSessionStreamLogic
    sessionConnectionStatus: WizardConnectionStatus // wizardSessionStreamLogic
    installationProgress: InstallationProgress
    sessionIsCurrent: boolean
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface installationProgressLogicActions {
    reportWizardSyncSessionDetected: (props: {
        runPhase: string
        skillId: string
        taskCount: number
        workflowId: string
    }) => {
        runPhase: string
        skillId: string
        taskCount: number
        workflowId: string
    } // eventUsageLogic
    reportWizardSyncSessionFinished: (props: {
        completedTaskCount: number
        elapsedSeconds: number
        outcome: string
        skillId: string
        taskCount: number
        workflowId: string
    }) => {
        completedTaskCount: number
        elapsedSeconds: number
        outcome: string
        skillId: string
        taskCount: number
        workflowId: string
    } // eventUsageLogic
    recordFinishedLocalRun: (session: WizardSessionDTOApi) => {
        session: WizardSessionDTOApi
    } // finishedLocalRunLogic
    supersedeFinishedLocalRun: (sessionId: string) => {
        sessionId: string
    } // finishedLocalRunLogic
    connectTaskRun: () => {
        value: true
    } // taskRunStreamLogic
    disconnectTaskRun: () => {
        value: true
    } // taskRunStreamLogic
    taskRunStreamCompleted: () => {
        value: true
    } // taskRunStreamLogic
    connectSession: () => {
        value: true
    } // wizardSessionStreamLogic
    disconnectSession: () => {
        value: true
    } // wizardSessionStreamLogic
    sessionUpdated: (session: WizardSessionDTOApi) => {
        session: WizardSessionDTOApi
    } // wizardSessionStreamLogic
    handoffDocReceived: (doc: { key: string; startedByEmail: string | null; text: string }) => {
        key: string
        startedByEmail: string | null
        text: string
    } // wizardSyncUiLogic
    markSessionCurrent: () => {
        value: true
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface installationProgressLogicMeta {
    key: string
    __keaTypeGenInternalSelectorTypes: {
        installationProgress: (
            taskRunState: TaskRunStreamState | null,
            progressSteps: TaskRunProgressStep[],
            taskConnectionStatus: TaskRunConnectionStatus,
            latestSession: WizardSessionDTOApi | null,
            sessionConnectionStatus: WizardConnectionStatus,
            sessionIsCurrent: boolean,
            isStalled: boolean,
            dismissedSessionId: string | null,
            activeCloudRun: CloudRunHandle | null,
            arg: any,
            arg2: any
        ) => InstallationProgress
    }
}

export type installationProgressLogicType = MakeLogicType<
    installationProgressLogicValues,
    installationProgressLogicActions,
    InstallationProgressLogicProps,
    installationProgressLogicMeta
>

/**
 * The Installation layer: one normalized `InstallationProgress` the UI renders, hiding which underlying
 * stream(s) feed it.
 *   - `mode: 'local'` — the wizard session stream only (the local CLI is the writer).
 *   - `mode: 'cloud'` — the TaskRun pipeline (provision → clone → wizard → agent → PR, plus terminal
 *     status, PR url, error) merged with the wizard session stream (wizard-stage detail).
 *
 * Both sources are always connected; in local mode the task source is a no-op (empty runId), so the
 * merge selector can reference its values unconditionally and just branch on `mode`.
 */
export const installationProgressLogic = kea<installationProgressLogicType>([
    props({} as InstallationProgressLogicProps),
    // Must include the workflow: kea mutates props in place on a cache hit, so two workflows sharing
    // a key would leave the second one's `connect` wiring pinned to the first one's stream.
    key(instanceKey),
    path((key) => ['scenes', 'onboarding', 'installationProgressLogic', key]),
    connect((props: InstallationProgressLogicProps) => ({
        values: [
            taskRunStreamLogic({ runId: props.runId ?? '', taskId: props.taskId ?? '' }),
            [
                'taskRunState',
                'progressSteps',
                'connectionStatus as taskConnectionStatus',
                'isStalled',
                'lastActivityAt',
            ],
            wizardSessionStreamLogic({ workflowId: resolveWorkflowId(props.workflowId) }),
            ['latestSession', 'connectionStatus as sessionConnectionStatus'],
            finishedLocalRunLogic,
            ['dismissedSessionId'],
            activeCloudRunLogic,
            ['activeCloudRun'],
        ],
        actions: [
            taskRunStreamLogic({ runId: props.runId ?? '', taskId: props.taskId ?? '' }),
            [
                'connect as connectTaskRun',
                'disconnect as disconnectTaskRun',
                'streamCompleted as taskRunStreamCompleted',
            ],
            wizardSessionStreamLogic({ workflowId: resolveWorkflowId(props.workflowId) }),
            ['connect as connectSession', 'disconnect as disconnectSession', 'sessionUpdated'],
            eventUsageLogic,
            ['reportWizardSyncSessionDetected', 'reportWizardSyncSessionFinished'],
            finishedLocalRunLogic,
            ['recordFinishedLocalRun', 'supersedeFinishedLocalRun'],
            wizardSyncUiLogic,
            ['handoffDocReceived'],
        ],
    })),
    actions({
        // Sticky flag — set the first time we observe a session that's recent enough to count as
        // live. Old terminal sessions sitting in the DB stay invisible to the install step.
        markSessionCurrent: true,
    }),
    reducers({
        sessionIsCurrent: [
            false,
            {
                markSessionCurrent: () => true,
            },
        ],
    }),
    selectors({
        installationProgress: [
            (s) => [
                s.taskRunState,
                s.progressSteps,
                s.taskConnectionStatus,
                s.latestSession,
                s.sessionConnectionStatus,
                s.sessionIsCurrent,
                s.isStalled,
                s.dismissedSessionId,
                s.activeCloudRun,
                (_, props) => props.mode,
                (_, props) => props.runId,
            ],
            (
                taskRunState: TaskRunStreamState | null,
                progressSteps: TaskRunProgressStep[],
                taskConnectionStatus: import('./taskRunStreamLogic').TaskRunConnectionStatus,
                latestSession: WizardSessionDTOApi | null,
                sessionConnectionStatus: import('products/wizard/frontend/wizardSessionStreamLogic').WizardConnectionStatus,
                sessionIsCurrent: boolean,
                isStalled: boolean,
                dismissedSessionId: string | null,
                activeCloudRun: CloudRunHandle | null,
                mode,
                runId
            ): InstallationProgress =>
                mode === 'cloud'
                    ? cloudProgress(
                          taskRunState,
                          progressSteps,
                          taskConnectionStatus,
                          latestSession,
                          isStalled,
                          Date.now(),
                          // The kickoff stamp scopes the handoff doc to this run (see cloudProgress);
                          // a handle for a different run means no window rather than a wrong one.
                          activeCloudRun?.runId === runId ? (activeCloudRun?.startedAt ?? null) : null
                      )
                    : localProgress(
                          latestSession,
                          sessionConnectionStatus,
                          sessionIsCurrent,
                          !!latestSession && latestSession.session_id === dismissedSessionId
                      ),
        ],
    }),
    listeners(({ actions, props, cache }) => ({
        // Once the cloud run is terminal there is nothing left for the session source to enrich —
        // release this instance's share so an undismissed finished run doesn't keep a session
        // stream/poll alive app-wide. The share accounting protects a co-mounted local instance,
        // whose "Run it yourself" recovery flow must outlive a finishing cloud run.
        taskRunStreamCompleted: () => {
            if (props.mode !== 'cloud') {
                return
            }
            releaseSessionShare(sessionStreamKey(props), instanceKey(props), actions.disconnectSession)
        },
        // Local-run bookkeeping, owned by the single local-mode instance so cloud instances (which
        // share the session stream purely for wizard-stage detail) don't double-fire it.
        sessionUpdated: ({ session }) => {
            if (props.mode !== 'local') {
                return
            }
            const prev = (cache.prevSession ?? null) as WizardSessionDTOApi | null
            cache.prevSession = session
            runLocalSessionBookkeeping(session, prev, resolveWorkflowId(props.workflowId), actions)
        },
    })),
    afterMount(({ actions, props, cache, values }) => {
        actions.connectTaskRun()
        acquireSessionShare(sessionStreamKey(props), instanceKey(props))
        actions.connectSession()
        if (props.mode === 'local') {
            // The detector's REST poll is only useful to the local instance (it gates the FAB's
            // local stream and receives markActive sync) — mounting it from cloud instances would
            // run a background poll for the whole run for nothing (INC-886 family).
            cache.unwatchWorkflow = watchWorkflowWhileMounted(resolveWorkflowId(props.workflowId))
            // Seed from a session already on the shared stream: the listener only sees NEW
            // deliveries, so a remount would otherwise wait for the next tick (long in polling
            // backoff) and flap the install-step takeover back to the command block.
            if (values.latestSession) {
                cache.prevSession = values.latestSession
                runLocalSessionBookkeeping(values.latestSession, null, resolveWorkflowId(props.workflowId), actions)
            }
        }
    }),
    beforeUnmount(({ actions, props, cache }) => {
        actions.disconnectTaskRun()
        releaseSessionShare(sessionStreamKey(props), instanceKey(props), actions.disconnectSession)
        if (cache.unwatchWorkflow) {
            cache.unwatchWorkflow()
            cache.unwatchWorkflow = undefined
        }
    }),
])

// The local instance's per-delivery bookkeeping, shared by the sessionUpdated listener and the
// mount-time seed:
//   - freshness: flip the sticky current flag so the install step can take over
//   - reach/outcome telemetry, once per session_id (module-scoped guards survive remounts)
//   - detector sync: keep the FAB's stream gate alive across navigation, and let a terminal
//     session schedule its teardown grace window
//   - finished-run handle: snapshot a fresh terminal run so its handoff surface outlives the
//     stream, and supersede the previous run's handle once a new run goes live
//   - handoff doc: announce a fresh session's doc so the one-time auto-open dialog can fire
export function runLocalSessionBookkeeping(
    session: WizardSessionDTOApi,
    prev: WizardSessionDTOApi | null,
    workflowId: string,
    actions: {
        markSessionCurrent: () => void
        recordFinishedLocalRun: (session: WizardSessionDTOApi) => void
        supersedeFinishedLocalRun: (sessionId: string) => void
        handoffDocReceived: (doc: { key: string; text: string; startedByEmail: string | null }) => void
        reportWizardSyncSessionDetected: (props: {
            workflowId: string
            skillId: string
            runPhase: string
            taskCount: number
        }) => void
        reportWizardSyncSessionFinished: (props: {
            workflowId: string
            skillId: string
            outcome: string
            taskCount: number
            completedTaskCount: number
            elapsedSeconds: number
        }) => void
    }
): void {
    const now = Date.now()
    // Tolerate a malformed delivery: reducers already stored the session, and throwing here would
    // silently skip the detector/telemetry bookkeeping for this update.
    const tasks = session.tasks ?? []
    const isTerminalPhase = session.run_phase === 'completed' || session.run_phase === 'error'
    if (isSessionFresh(session, now)) {
        actions.markSessionCurrent()
        // The handoff surface must outlive the stream (the detector gates it off shortly after a
        // terminal phase): snapshot fresh terminal runs, and let a fresh run going live supersede
        // a previous run's snapshot.
        if (isTerminalPhase) {
            actions.recordFinishedLocalRun(session)
        } else {
            actions.supersedeFinishedLocalRun(session.session_id)
        }
        // Freshness-gated like the rest: a stale row's doc was either seen already or belongs to a
        // run nobody is watching. The seen-keys guard makes redeliveries a no-op. Completed only:
        // the buttons that reopen the doc are gated on the completed phase, so announcing it for an
        // errored run would burn the one auto-open on a dialog the user can never get back to.
        if (
            session.run_phase === 'completed' &&
            typeof session.handoff_text === 'string' &&
            session.handoff_text.length > 0
        ) {
            actions.handoffDocReceived({
                key: session.session_id,
                text: session.handoff_text,
                startedByEmail: session.created_by?.email ?? null,
            })
        }
        // Reach metric: count each live wizard session the sync surfaces, once per session_id.
        // Gated on freshness so stale terminal rows sitting in the DB — which never reach the
        // user — don't inflate the funnel.
        if (!reportedDetectedSessions.has(session.session_id)) {
            reportedDetectedSessions.add(session.session_id)
            actions.reportWizardSyncSessionDetected({
                workflowId,
                skillId: session.skill_id,
                runPhase: session.run_phase,
                taskCount: tasks.length,
            })
        }
    }
    // Gate on the detector's shared eligibility predicate (server staleness + lifetime cap +
    // terminal phase) so the SSE and REST paths agree on when streaming may continue — a wedged
    // CLI heartbeating `updated_at` past the lifetime cap stops re-arming markActive, letting
    // teardown actually run. Only schedule teardown on the eligible → ineligible *transition* so
    // repeated re-polls don't reset the clock. The detector is mounted by the local instance's
    // afterMount, which always precedes this bookkeeping.
    const detector = wizardActiveSessionDetectorLogic.findMounted()
    if (detector) {
        const eligible = isSessionActive(session)
        const wasEligible = isSessionActive(prev)
        if (eligible) {
            detector.actions.markActive(workflowId)
        } else if (wasEligible) {
            detector.actions.scheduleMarkInactive()
        }
    }
    // Outcome metric: fire once when a run the user watched live reaches a terminal phase.
    // Terminal phases are sticky, so this transition is observed at most once per session — the
    // id guard covers any SSE redelivery.
    if (prev && session.run_phase !== prev.run_phase) {
        if (isTerminalPhase && !reportedFinishedSessions.has(session.session_id)) {
            reportedFinishedSessions.add(session.session_id)
            actions.reportWizardSyncSessionFinished({
                workflowId,
                skillId: session.skill_id,
                outcome: session.run_phase,
                taskCount: tasks.length,
                completedTaskCount: tasks.filter((t) => t.status === 'completed').length,
                elapsedSeconds: elapsedSecondsFrom(session.started_at, now),
            })
        }
    }
}

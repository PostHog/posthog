import { actions, afterMount, beforeUnmount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import { elapsedSecondsFrom } from 'lib/utils/datetime'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

import type { WizardSessionDTOApi } from 'products/wizard/frontend/generated/api.schemas'
import { wizardSessionStreamLogic } from 'products/wizard/frontend/wizardSessionStreamLogic'

import { activeCloudRunLogic } from './activeCloudRunLogic'
import { finishedLocalRunLogic, FinishedLocalRunHandle } from './finishedLocalRunLogic'
import type { installationProgressLogicType } from './installationProgressLogicType'
import {
    taskRunPrMerged,
    taskRunPrUrl,
    taskRunStreamLogic,
    TaskRunProgressStep,
    TaskRunStreamState,
} from './taskRunStreamLogic'
import { isSessionActive, wizardActiveSessionDetectorLogic } from './wizardActiveSessionDetectorLogic'
import { wizardDashboardLogic } from './wizardDashboardLogic'

// The wizard session stream the local CLI publishes to — and the channel a cloud wizard reports its
// own sub-progress on.
const WORKFLOW_ID = 'posthog-integration'

// A session counts as "current" if it was updated within the last 10 minutes. Lets the install step
// ignore stale terminal sessions left over from previous runs / test data when a user lands on the
// app, while still re-surfacing recently-completed runs after a quick navigation away and back.
const SESSION_CURRENT_THRESHOLD_MS = 10 * 60 * 1000

export function isSessionFresh(session: WizardSessionDTOApi, now: number): boolean {
    const updatedAt = new Date(session.updated_at).getTime()
    return !Number.isNaN(updatedAt) && now - updatedAt < SESSION_CURRENT_THRESHOLD_MS
}

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
const sessionStreamShares = new Set<string>()

function releaseSessionShare(shareKey: string, disconnectSession: () => void): void {
    if (!sessionStreamShares.delete(shareKey)) {
        return
    }
    if (sessionStreamShares.size === 0) {
        disconnectSession()
    }
}

export function resetWizardSyncTelemetryForTests(): void {
    reportedDetectedSessions.clear()
    reportedFinishedSessions.clear()
    sessionStreamShares.clear()
}

function instanceKey(props: InstallationProgressLogicProps): string {
    return props.mode === 'cloud' ? `cloud:${props.runId ?? ''}` : 'local'
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

export interface InstallationProgress {
    phase: InstallationPhase
    steps: InstallationStep[]
    error: { title: string; detail: string | null } | null
    prUrl: string | null
    /** The bound PR was merged (webhook-recorded on the run's output). */
    prMerged: boolean
    isCurrent: boolean
}

export interface InstallationProgressLogicProps {
    mode: InstallationMode
    runId?: string
    taskId?: string
}

const STEP_STATUSES: Record<string, InstallationStepStatus> = {
    pending: 'pending',
    in_progress: 'in_progress',
    completed: 'completed',
    failed: 'failed',
    canceled: 'failed',
}

// The stages every cloud run walks, in order — the timeline's fixed plan. Labels match the
// connecting preview (UPCOMING_STEPS) so the handoff between the two is seamless; announced steps
// override them with the backend's own labels.
const CLOUD_PIPELINE_SKELETON: { group: string; step: string; label: string }[] = [
    { group: 'setup', step: 'sandbox', label: 'Setting up sandbox' },
    { group: 'setup', step: 'clone', label: 'Cloning repository' },
    { group: 'setup', step: 'wizard', label: 'Running setup wizard' },
    { group: 'deliver', step: 'pr', label: 'Opening a pull request' },
]

function stepStatus(raw: string): InstallationStepStatus {
    return STEP_STATUSES[raw] ?? 'pending'
}

// Cloud: the TaskRun is the spine (phase, steps, PR url, terminal error); the wizard session's own
// tasks expand into the timeline as wizard-sourced steps nested after the pipeline's wizard stage
// (absent while the cloud wizard hasn't reported yet — degrades to the bare TaskRun pipeline).
export function cloudProgress(
    taskRunState: TaskRunStreamState | null,
    progressSteps: TaskRunProgressStep[],
    taskConnectionStatus: string,
    latestSession: WizardSessionDTOApi | null,
    isStalled: boolean = false,
    now: number = Date.now()
): InstallationProgress {
    let phase: InstallationPhase
    let stalledError: { title: string; detail: string | null } | null = null
    if (!taskRunState) {
        phase = taskConnectionStatus === 'connecting' ? 'connecting' : 'idle'
    } else if (taskRunState.status === 'queued' && isStalled) {
        // The run never left the queue (see taskRunStreamLogic's stall timer) — nothing is actually
        // running, so an eternal spinner would be a lie.
        phase = 'error'
        stalledError = {
            title: "Setup hasn't started",
            detail: 'The run has been queued for a while without starting. Please try again in a bit.',
        }
    } else if (taskRunState.status === 'completed') {
        phase = 'completed'
    } else if (taskRunState.status === 'failed' || taskRunState.status === 'cancelled') {
        phase = 'error'
    } else if (taskRunState.status === 'queued') {
        // Queued means nothing has started yet — "getting ready", not "running".
        phase = 'connecting'
    } else {
        phase = 'running'
    }

    // A completed run has nothing in flight: clamp a lingering in-progress step (e.g. "Keeping
    // CI green", emitted in-progress when the PR opened) to completed so the timeline matches.
    const clamp = (status: InstallationStepStatus): InstallationStepStatus =>
        phase === 'completed' && status === 'in_progress' ? 'completed' : status

    // 'Started agent' is internal plumbing — it tells the user nothing about their setup. Hide it;
    // the pending "Opening a pull request" row (flipped in-progress below) narrates that window.
    const announced = progressSteps.filter((p) => p.step !== 'agent')
    const mapStep = (p: TaskRunProgressStep): InstallationStep => ({
        id: `${p.group}:${p.step}`,
        label: p.label,
        status: clamp(stepStatus(p.status)),
        // The "pr" step carries the PR url in `detail` (surfaced as the CTA, not as raw step text).
        detail: p.step === 'pr' ? null : p.detail,
    })
    // Every cloud run walks the same pipeline, so the whole plan is visible from the start as
    // pending rows — announced steps light their slot up in place (keeping the backend's label and
    // detail), and anything outside the skeleton (e.g. "Keeping CI green") appends in arrival
    // order. Skipped when no run state exists yet: the view's connecting preview owns that window.
    let pipelineSteps: InstallationStep[]
    if (taskRunState) {
        const byName = new Map(announced.map((p) => [p.step, p]))
        pipelineSteps = CLOUD_PIPELINE_SKELETON.map((sk) => {
            const real = byName.get(sk.step)
            return real
                ? mapStep(real)
                : { id: `${sk.group}:${sk.step}`, label: sk.label, status: 'pending' as const, detail: null }
        })
        const skeletonNames = new Set(CLOUD_PIPELINE_SKELETON.map((sk) => sk.step))
        pipelineSteps.push(...announced.filter((p) => !skeletonNames.has(p.step)).map(mapStep))
    } else {
        pipelineSteps = announced.map(mapStep)
    }

    // The session stream is keyed by workflow only and replays the latest session on connect even
    // when it's a stale terminal row from a previous (possibly local) run — apply the same freshness
    // gate the local path uses before letting it near this run's timeline or error detail. A fresh
    // unrelated session can still slip in (the cloud wizard posts to the same workflow by design).
    const session = latestSession && isSessionFresh(latestSession, now) ? latestSession : null

    // The cloud wizard reports its own sub-steps on the session stream — once they exist they
    // REPLACE the pipeline's aggregate "wizard" stage in the timeline (the tasks are that stage,
    // told in more detail). Until then the stage row stands in. When the stage hasn't been
    // announced at all (e.g. polling mode where step notifications are stream-borne), slot the
    // tasks before the first not-yet-completed pipeline step so in-flight wizard work never
    // renders after the PR stage.
    const wizardSteps: InstallationStep[] = (session?.tasks ?? []).map((t) => ({
        id: `wizard-task:${t.id}`,
        label: t.title,
        status: clamp(stepStatus(t.status)),
        detail: null,
        source: 'wizard',
    }))
    const wizardStageIndex = pipelineSteps.findIndex((s) => s.id.endsWith(':wizard'))
    let steps: InstallationStep[]
    if (wizardStageIndex !== -1 && wizardSteps.length > 0) {
        steps = [
            ...pipelineSteps.slice(0, wizardStageIndex),
            ...wizardSteps,
            ...pipelineSteps.slice(wizardStageIndex + 1),
        ]
    } else if (wizardSteps.length > 0) {
        const firstUnfinished = pipelineSteps.findIndex((s) => s.status !== 'completed')
        const insertIndex = firstUnfinished === -1 ? pipelineSteps.length : firstUnfinished
        steps = [...pipelineSteps.slice(0, insertIndex), ...wizardSteps, ...pipelineSteps.slice(insertIndex)]
    } else {
        steps = pipelineSteps
    }

    const prUrl = taskRunPrUrl(taskRunState, progressSteps)
    const prMerged = taskRunPrMerged(taskRunState)

    // The pipeline goes quiet between agent start and the PR opening: everything reads completed
    // while the agent is still writing code, committing, and drafting the PR — which looks stalled.
    // Flip the still-pending PR slot to in-progress with an honest detail line for that window; the
    // real deliver-stage step replaces it when it arrives.
    const allDoneExceptPr = steps.every((s) => s.id.endsWith(':pr') || s.status === 'completed')
    if (phase === 'running' && !prUrl && allDoneExceptPr) {
        steps = steps.map((s) =>
            s.id.endsWith(':pr') && s.status === 'pending'
                ? {
                      ...s,
                      status: 'in_progress' as const,
                      detail: 'The agent is committing its changes and drafting the PR',
                  }
                : s
        )
    }

    const error =
        phase === 'error'
            ? (stalledError ?? {
                  title: 'Installation failed',
                  detail:
                      taskRunState?.error_message ?? (session?.error as { message?: string } | null)?.message ?? null,
              })
            : null

    return {
        phase,
        steps,
        error,
        prUrl,
        prMerged,
        isCurrent: phase !== 'idle',
    }
}

// Local: the wizard session is the only source. `sessionIsCurrent` is the sticky freshness flag —
// the SSE replays the latest session on connect even when it's a stale terminal row from a previous
// run, and those must not read as a run in flight. `dismissed` is the user's explicit dismissal of
// this session — it wins over freshness, so a dismissed run releases the install-step takeover.
export function localProgress(
    latestSession: WizardSessionDTOApi | null,
    sessionConnectionStatus: string,
    sessionIsCurrent: boolean,
    dismissed: boolean = false
): InstallationProgress {
    if (!latestSession) {
        return {
            phase: sessionConnectionStatus === 'connecting' ? 'connecting' : 'idle',
            steps: [],
            error: null,
            prUrl: null,
            prMerged: false,
            isCurrent: false,
        }
    }

    let phase: InstallationPhase
    if (latestSession.run_phase === 'completed') {
        phase = 'completed'
    } else if (latestSession.run_phase === 'error') {
        phase = 'error'
    } else if (sessionConnectionStatus === 'connecting' || sessionConnectionStatus === 'error') {
        phase = 'connecting'
    } else {
        phase = 'running'
    }

    const steps: InstallationStep[] = (latestSession.tasks ?? []).map((t) => ({
        id: t.id,
        label: t.title,
        status: stepStatus(t.status),
        detail: null,
    }))

    const error =
        latestSession.run_phase === 'error'
            ? {
                  title: 'Wizard hit an error',
                  detail: (latestSession.error as { message?: string } | null)?.message ?? null,
              }
            : null

    return { phase, steps, error, prUrl: null, prMerged: false, isCurrent: sessionIsCurrent && !dismissed }
}

// A finished local run rendered from its persisted snapshot, after the live session stream has
// gated itself off — same shape the live path produces for the same terminal session.
export function progressFromFinishedLocalRun(handle: FinishedLocalRunHandle): InstallationProgress {
    return {
        phase: handle.runPhase,
        steps: handle.tasks.map((t) => ({ id: t.id, label: t.title, status: stepStatus(t.status), detail: null })),
        error:
            handle.runPhase === 'error'
                ? { title: 'Wizard hit an error', detail: handle.error?.message ?? null }
                : null,
        prUrl: null,
        prMerged: false,
        isCurrent: true,
    }
}

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
    key((props) => (props.mode === 'cloud' ? `cloud:${props.runId ?? ''}` : 'local')),
    path((key) => ['scenes', 'onboarding', 'installationProgressLogic', key]),
    connect((props: InstallationProgressLogicProps) => ({
        values: [
            taskRunStreamLogic({ runId: props.runId ?? '', taskId: props.taskId ?? '' }),
            ['taskRunState', 'progressSteps', 'connectionStatus as taskConnectionStatus', 'isStalled'],
            wizardSessionStreamLogic({ workflowId: WORKFLOW_ID }),
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
            wizardSessionStreamLogic({ workflowId: WORKFLOW_ID }),
            ['connect as connectSession', 'disconnect as disconnectSession', 'sessionUpdated'],
            eventUsageLogic,
            ['reportWizardSyncSessionDetected', 'reportWizardSyncSessionFinished'],
            finishedLocalRunLogic,
            ['recordFinishedLocalRun', 'supersedeFinishedLocalRun'],
            wizardDashboardLogic,
            ['detectWizardDashboard'],
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
                (_, props) => props.mode,
            ],
            (
                taskRunState,
                progressSteps,
                taskConnectionStatus,
                latestSession,
                sessionConnectionStatus,
                sessionIsCurrent,
                isStalled,
                dismissedSessionId,
                mode
            ): InstallationProgress =>
                mode === 'cloud'
                    ? cloudProgress(taskRunState, progressSteps, taskConnectionStatus, latestSession, isStalled)
                    : localProgress(
                          latestSession,
                          sessionConnectionStatus,
                          sessionIsCurrent,
                          !!latestSession && latestSession.session_id === dismissedSessionId
                      ),
        ],
    }),
    listeners(({ actions, props, cache, values }) => ({
        // Once the cloud run is terminal there is nothing left for the session source to enrich —
        // release this instance's share so an undismissed finished run doesn't keep a session
        // stream/poll alive app-wide. The share accounting protects a co-mounted local instance,
        // whose "Run it yourself" recovery flow must outlive a finishing cloud run.
        taskRunStreamCompleted: () => {
            if (props.mode !== 'cloud') {
                return
            }
            releaseSessionShare(instanceKey(props), actions.disconnectSession)
            // The cloud wizard builds a dashboard too — look it up so the completed surfaces can
            // link to it. startedAt travels on the persisted run handle; without it there's no run
            // window to scope the search to, so skip.
            const startedAt =
                values.activeCloudRun?.runId === props.runId ? values.activeCloudRun?.startedAt : undefined
            if (values.taskRunState?.status === 'completed' && startedAt) {
                actions.detectWizardDashboard({ startedAt })
            }
        },
        // Local-run bookkeeping, owned by the single local-mode instance so cloud instances (which
        // share the session stream purely for wizard-stage detail) don't double-fire it.
        sessionUpdated: ({ session }) => {
            if (props.mode !== 'local') {
                return
            }
            const prev = (cache.prevSession ?? null) as WizardSessionDTOApi | null
            cache.prevSession = session
            runLocalSessionBookkeeping(session, prev, actions)
        },
    })),
    afterMount(({ actions, props, cache, values }) => {
        actions.connectTaskRun()
        sessionStreamShares.add(instanceKey(props))
        actions.connectSession()
        if (props.mode === 'local') {
            // The detector's REST poll is only useful to the local instance (it gates the FAB's
            // local stream and receives markActive sync) — mounting it from cloud instances would
            // run a background poll for the whole run for nothing (INC-886 family).
            cache.detectorUnmount = wizardActiveSessionDetectorLogic.mount()
            // Seed from a session already on the shared stream: the listener only sees NEW
            // deliveries, so a remount would otherwise wait for the next tick (long in polling
            // backoff) and flap the install-step takeover back to the command block.
            if (values.latestSession) {
                cache.prevSession = values.latestSession
                runLocalSessionBookkeeping(values.latestSession, null, actions)
            }
        }
    }),
    beforeUnmount(({ actions, props, cache }) => {
        actions.disconnectTaskRun()
        releaseSessionShare(instanceKey(props), actions.disconnectSession)
        if (cache.detectorUnmount) {
            cache.detectorUnmount()
            cache.detectorUnmount = undefined
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
export function runLocalSessionBookkeeping(
    session: WizardSessionDTOApi,
    prev: WizardSessionDTOApi | null,
    actions: {
        markSessionCurrent: () => void
        recordFinishedLocalRun: (session: WizardSessionDTOApi) => void
        supersedeFinishedLocalRun: (sessionId: string) => void
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
        // Reach metric: count each live wizard session the sync surfaces, once per session_id.
        // Gated on freshness so stale terminal rows sitting in the DB — which never reach the
        // user — don't inflate the funnel.
        if (!reportedDetectedSessions.has(session.session_id)) {
            reportedDetectedSessions.add(session.session_id)
            actions.reportWizardSyncSessionDetected({
                workflowId: WORKFLOW_ID,
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
            detector.actions.markActive()
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
                workflowId: WORKFLOW_ID,
                skillId: session.skill_id,
                outcome: session.run_phase,
                taskCount: tasks.length,
                completedTaskCount: tasks.filter((t) => t.status === 'completed').length,
                elapsedSeconds: elapsedSecondsFrom(session.started_at, now),
            })
        }
    }
}

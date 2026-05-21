import { Meta, StoryFn } from '@storybook/react'
import { useMountedLogic } from 'kea'
import { useEffect, useRef } from 'react'

import { wizardSessionStreamLogic } from 'products/wizard/frontend/wizardSessionStreamLogic'

import { WizardProgressTracker } from './WizardProgressTracker'
import { wizardProgressTrackerLogic } from './wizardProgressTrackerLogic'

const WORKFLOW_ID = 'posthog-integration'
const SKILL_ID = 'laravel'

/**
 * Stub `EventSource` at module load time, before any kea logic mounts. The
 * real SSE endpoint can't be reached from Storybook; with this stub the
 * stream-opening listener succeeds silently and our stories drive state by
 * dispatching the same actions the real EventSource handlers would.
 */
if (typeof window !== 'undefined' && !(window as any).__wizardEventSourceStubbed) {
    class StubEventSource {
        readyState = 0
        url = ''
        withCredentials = false
        onopen: ((ev: Event) => void) | null = null
        onmessage: ((ev: MessageEvent) => void) | null = null
        onerror: ((ev: Event) => void) | null = null
        addEventListener(): void {}
        removeEventListener(): void {}
        dispatchEvent(): boolean {
            return false
        }
        close(): void {}
        static readonly CONNECTING = 0
        static readonly OPEN = 1
        static readonly CLOSED = 2
    }
    ;(window as any).EventSource = StubEventSource
    ;(window as any).__wizardEventSourceStubbed = true
}

type WizardSessionFixture = {
    session_id: string
    team_id: number
    workflow_id: string
    skill_id: string
    started_at: string
    run_phase: 'idle' | 'running' | 'completed' | 'error'
    tasks: Array<{
        id: string
        title: string
        status: 'pending' | 'in_progress' | 'completed' | 'failed' | 'cancelled'
    }>
    event_plan: unknown | null
    error: { type: string; message: string } | null
    created_at: string
    updated_at: string
}

function makeSession(overrides: Partial<WizardSessionFixture>): WizardSessionFixture {
    const startedAt = new Date(Date.now() - 30_000).toISOString()
    return {
        session_id: `${WORKFLOW_ID}-${SKILL_ID}-${startedAt}`,
        team_id: 1,
        workflow_id: WORKFLOW_ID,
        skill_id: SKILL_ID,
        started_at: startedAt,
        run_phase: 'running',
        tasks: [],
        event_plan: null,
        error: null,
        created_at: startedAt,
        updated_at: new Date().toISOString(),
        ...overrides,
    }
}

const SAMPLE_TASKS = [
    { id: '1', title: 'Install posthog-node package' },
    { id: '2', title: 'Set up PostHog environment variables' },
    { id: '3', title: 'Create PostHog client module' },
    { id: '4', title: 'Insert event tracking in API handlers' },
    { id: '5', title: 'Wrapping up' },
] as const

type TaskStatus = WizardSessionFixture['tasks'][number]['status']

function buildTasks(statuses: TaskStatus[]): WizardSessionFixture['tasks'] {
    return SAMPLE_TASKS.map((t, i) => ({ ...t, status: statuses[i] ?? 'pending' }))
}

/**
 * Container that pushes a single session snapshot into the stream logic on
 * mount. Used by the static stories (Analyzing / Running / Completed / Error).
 */
function withSession(session: WizardSessionFixture | null): StoryFn {
    return function StoryRender() {
        useMountedLogic(wizardProgressTrackerLogic)
        const streamLogic = wizardSessionStreamLogic({ workflowId: WORKFLOW_ID })
        useMountedLogic(streamLogic)

        useEffect(() => {
            streamLogic.actions.connectionOpened()
            if (session) {
                streamLogic.actions.sessionUpdated(session as any)
            }
            // Mount once. We intentionally don't react to identity changes.
            // eslint-disable-next-line react-hooks/exhaustive-deps
        }, [])

        return (
            <SceneFrame>
                <WizardProgressTracker onManualSetup={() => alert('Open manual setup modal')} />
            </SceneFrame>
        )
    }
}

const meta: Meta = {
    title: 'Scenes-Other/Onboarding/Wizard Progress Tracker',
    component: WizardProgressTracker,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
    },
}
export default meta

/**
 * Visual frame that mimics the onboarding Install step's content area, so the
 * panel is shown the way users actually see it.
 */
function SceneFrame({ children }: { children: React.ReactNode }): JSX.Element {
    return (
        <div className="min-h-screen bg-bg-light text-default px-6 py-10">
            <div className="max-w-4xl mx-auto">
                <h1 className="text-2xl font-bold mb-1">Install</h1>
                <p className="text-muted mb-8">
                    The AI wizard is installing PostHog into your project. You can keep working in the meantime —
                    we&apos;ll update this view as it makes progress.
                </p>
                <div className="max-w-3xl mx-auto">{children}</div>
            </div>
        </div>
    )
}

/** Pre-takeover: no session yet. Tracker should render nothing. */
export const PreTakeover: StoryFn = withSession(null)

/** Session arrived, no tasks yet — the 1–2min analyze gap. */
export const Analyzing: StoryFn = withSession(
    makeSession({
        run_phase: 'running',
        tasks: [],
    })
)

/** Mid-run: one task in_progress, two completed behind it. */
export const Running: StoryFn = withSession(
    makeSession({
        run_phase: 'running',
        tasks: buildTasks(['completed', 'completed', 'in_progress', 'pending', 'pending']),
    })
)

/** All tasks finished. */
export const Completed: StoryFn = withSession(
    makeSession({
        run_phase: 'completed',
        tasks: buildTasks(['completed', 'completed', 'completed', 'completed', 'completed']),
    })
)

/** Wizard hit an error mid-task. Error block + manual-setup link visible. */
export const Errored: StoryFn = withSession(
    makeSession({
        run_phase: 'error',
        tasks: buildTasks(['completed', 'completed', 'failed', 'cancelled', 'cancelled']),
        error: {
            type: 'CompositionError',
            message: 'Could not detect a writable .env file. Re-run from the project root and try again.',
        },
    })
)

/** Connection error mid-run; last good state is sticky. */
export const Reconnecting: StoryFn = function ReconnectingStory() {
    useMountedLogic(wizardProgressTrackerLogic)
    const streamLogic = wizardSessionStreamLogic({ workflowId: WORKFLOW_ID })
    useMountedLogic(streamLogic)

    useEffect(() => {
        streamLogic.actions.connectionOpened()
        streamLogic.actions.sessionUpdated(
            makeSession({
                run_phase: 'running',
                tasks: buildTasks(['completed', 'in_progress', 'pending', 'pending', 'pending']),
            }) as any
        )
        // Then drop the connection.
        const id = window.setTimeout(() => {
            streamLogic.actions.connectionErrored('EventSource transport error')
        }, 200)
        return () => window.clearTimeout(id)
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [])

    return (
        <SceneFrame>
            <WizardProgressTracker onManualSetup={() => alert('Open manual setup modal')} />
        </SceneFrame>
    )
}

/**
 * Auto-playing simulated wizard run. Steps through the realistic timeline:
 *   t=0s   session opens, tasks empty (analyze)
 *   t=4s   first task in_progress
 *   t=8s   first task completes, second starts
 *   t=12s  second completes, third starts
 *   t=16s  third completes, fourth starts
 *   t=20s  fourth completes, fifth starts
 *   t=24s  fifth completes, run_phase=completed
 *
 * Sit and watch — the panel will progress on its own. Click `set up manually →`
 * to test the escape hatch (alerts in this story).
 */
export const SimulatedRun: StoryFn = function SimulatedRunStory() {
    useMountedLogic(wizardProgressTrackerLogic)
    const streamLogic = wizardSessionStreamLogic({ workflowId: WORKFLOW_ID })
    useMountedLogic(streamLogic)

    const timersRef = useRef<number[]>([])

    useEffect(() => {
        const { actions } = streamLogic
        const startedAt = new Date().toISOString()
        const base: WizardSessionFixture = {
            session_id: `${WORKFLOW_ID}-${SKILL_ID}-${startedAt}`,
            team_id: 1,
            workflow_id: WORKFLOW_ID,
            skill_id: SKILL_ID,
            started_at: startedAt,
            run_phase: 'running',
            tasks: [],
            event_plan: null,
            error: null,
            created_at: startedAt,
            updated_at: startedAt,
        }

        actions.connectionOpened()
        actions.sessionUpdated(base as any)

        const schedule: Array<{ atMs: number; tasks: TaskStatus[]; phase?: 'running' | 'completed' }> = [
            { atMs: 4_000, tasks: ['in_progress', 'pending', 'pending', 'pending', 'pending'] },
            { atMs: 8_000, tasks: ['completed', 'in_progress', 'pending', 'pending', 'pending'] },
            { atMs: 12_000, tasks: ['completed', 'completed', 'in_progress', 'pending', 'pending'] },
            { atMs: 16_000, tasks: ['completed', 'completed', 'completed', 'in_progress', 'pending'] },
            { atMs: 20_000, tasks: ['completed', 'completed', 'completed', 'completed', 'in_progress'] },
            {
                atMs: 24_000,
                tasks: ['completed', 'completed', 'completed', 'completed', 'completed'],
                phase: 'completed',
            },
        ]

        timersRef.current = schedule.map(({ atMs, tasks, phase }) =>
            window.setTimeout(() => {
                actions.sessionUpdated({
                    ...base,
                    run_phase: phase ?? 'running',
                    tasks: buildTasks(tasks),
                    updated_at: new Date().toISOString(),
                } as any)
            }, atMs)
        )

        return () => {
            timersRef.current.forEach((id) => window.clearTimeout(id))
            timersRef.current = []
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [])

    return (
        <SceneFrame>
            <WizardProgressTracker onManualSetup={() => alert('Open manual setup modal')} />
        </SceneFrame>
    )
}

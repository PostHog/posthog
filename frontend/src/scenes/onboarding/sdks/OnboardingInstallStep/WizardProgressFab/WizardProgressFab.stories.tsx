import { Meta, StoryFn } from '@storybook/react'
import { useMountedLogic } from 'kea'
import { useEffect, useRef } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'

import { wizardSessionStreamLogic } from 'products/wizard/frontend/wizardSessionStreamLogic'

import { WizardProgressFab } from '.'
import { WIZARD_SKILL_IDS } from '../../skillBadge'
import { wizardProgressTrackerLogic } from '../wizardProgressTrackerLogic'

const WORKFLOW_ID = 'posthog-integration'
const DEFAULT_SKILL_ID = 'laravel'

const SKILL_OPTIONS: string[] = [...WIZARD_SKILL_IDS, 'unknown-skill']

interface StoryArgs {
    skillId: string
}

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

type TaskStatus = 'pending' | 'in_progress' | 'completed' | 'failed' | 'canceled'

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
        status: TaskStatus
    }>
    event_plan: unknown | null
    error: { type: string; message: string } | null
    created_at: string
    updated_at: string
}

const SAMPLE_TASKS = [
    { id: '1', title: 'Install posthog-node package' },
    { id: '2', title: 'Set up PostHog environment variables' },
    { id: '3', title: 'Create PostHog client module' },
    { id: '4', title: 'Insert event tracking in API handlers' },
    { id: '5', title: 'Wrapping up' },
] as const

function buildTasks(statuses: TaskStatus[]): WizardSessionFixture['tasks'] {
    return SAMPLE_TASKS.map((t, i) => ({ ...t, status: statuses[i] ?? 'pending' }))
}

function makeSession(overrides: Partial<WizardSessionFixture> = {}): WizardSessionFixture {
    const skill_id = overrides.skill_id ?? DEFAULT_SKILL_ID
    const startedAt = new Date(Date.now() - 74_000).toISOString()
    return {
        session_id: `${WORKFLOW_ID}-${skill_id}-${startedAt}`,
        team_id: 1,
        workflow_id: WORKFLOW_ID,
        skill_id,
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

function withSession(buildSession: (skillId: string) => WizardSessionFixture | null): StoryFn<StoryArgs> {
    return function StoryRender({ skillId }) {
        useMountedLogic(wizardProgressTrackerLogic)
        const streamLogic = wizardSessionStreamLogic({ workflowId: WORKFLOW_ID })
        useMountedLogic(streamLogic)

        useEffect(() => {
            streamLogic.actions.connectionOpened()
            const session = buildSession(skillId)
            if (session) {
                streamLogic.actions.sessionUpdated(session as any)
            }
            // eslint-disable-next-line react-hooks/exhaustive-deps
        }, [skillId])

        return (
            <SceneFrame>
                <WizardProgressFab />
            </SceneFrame>
        )
    }
}

const meta: Meta<StoryArgs> = {
    title: 'Scenes-Other/Onboarding/Wizard Progress FAB',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        // FAB is flag-gated; storybook's useFeatureFlag treats any truthy value as "on".
        featureFlags: [FEATURE_FLAGS.ONBOARDING_WIZARD_SYNC],
    },
    args: { skillId: DEFAULT_SKILL_ID },
    argTypes: {
        skillId: {
            control: { type: 'select' },
            options: SKILL_OPTIONS,
            description: 'Wizard skill_id — drives the session_id and any badge surface.',
        },
    },
}
export default meta

function SceneFrame({ children }: { children: React.ReactNode }): JSX.Element {
    return (
        <div className="min-h-screen bg-bg-light text-default px-6 py-10 relative">
            <div className="max-w-4xl mx-auto">
                <h1 className="text-2xl font-bold mb-1">Onboarding (some later step)</h1>
                <p className="text-muted mb-8">
                    The user has navigated away from the wizard install step. The FAB persists across the rest of the
                    onboarding flow until the run finishes — click it to jump back to the install step.
                </p>
            </div>
            {children}
        </div>
    )
}

/** No session — FAB renders nothing. */
export const Hidden: StoryFn<StoryArgs> = withSession(() => null)

/**
 * Live session in flight, but the user is on the install step — the inline confirmation
 * card has set `panelMounted: true`, so the FAB suppresses itself. Documents the
 * "card and FAB never overlap" contract.
 */
export const HiddenByPanel: StoryFn<StoryArgs> = function HiddenByPanelStory({ skillId }) {
    useMountedLogic(wizardProgressTrackerLogic)
    const streamLogic = wizardSessionStreamLogic({ workflowId: WORKFLOW_ID })
    useMountedLogic(streamLogic)

    useEffect(() => {
        streamLogic.actions.connectionOpened()
        streamLogic.actions.sessionUpdated(
            makeSession({
                skill_id: skillId,
                run_phase: 'running',
                tasks: buildTasks(['completed', 'in_progress', 'pending', 'pending', 'pending']),
            }) as any
        )
        wizardProgressTrackerLogic.actions.setPanelMounted(true)
        return () => wizardProgressTrackerLogic.actions.setPanelMounted(false)
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [skillId])

    return (
        <SceneFrame>
            <p className="max-w-4xl mx-auto text-sm text-muted italic">
                Imagine the install step is rendered here — the confirmation card has flagged itself mounted, so the FAB
                stays out of the way. You should see nothing in the corner below.
            </p>
        </SceneFrame>
    )
}

/** Wizard just kicked off, no tasks yet — ring spins (indeterminate). */
export const Analyzing: StoryFn<StoryArgs> = withSession((skillId) =>
    makeSession({
        skill_id: skillId,
        run_phase: 'running',
        tasks: [],
    })
)

/** Mid-run, ~40% done with a task currently running. */
export const RunningEarly: StoryFn<StoryArgs> = withSession((skillId) =>
    makeSession({
        skill_id: skillId,
        run_phase: 'running',
        tasks: buildTasks(['completed', 'completed', 'in_progress', 'pending', 'pending']),
    })
)

/** Late mid-run, ~80% done. Demonstrates the ring filling. */
export const RunningLate: StoryFn<StoryArgs> = withSession((skillId) =>
    makeSession({
        skill_id: skillId,
        run_phase: 'running',
        tasks: buildTasks(['completed', 'completed', 'completed', 'completed', 'in_progress']),
    })
)

/** Reconnecting state: live session mid-run, but the SSE transport just errored. */
export const Connecting: StoryFn<StoryArgs> = function ConnectingStory({ skillId }) {
    useMountedLogic(wizardProgressTrackerLogic)
    const streamLogic = wizardSessionStreamLogic({ workflowId: WORKFLOW_ID })
    useMountedLogic(streamLogic)

    useEffect(() => {
        streamLogic.actions.connectionOpened()
        streamLogic.actions.sessionUpdated(
            makeSession({
                skill_id: skillId,
                run_phase: 'running',
                tasks: buildTasks(['completed', 'in_progress', 'pending', 'pending', 'pending']),
            }) as any
        )
        const id = window.setTimeout(() => {
            streamLogic.actions.connectionErrored('EventSource transport error — reconnecting')
        }, 50)
        return () => window.clearTimeout(id)
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [skillId])

    return (
        <SceneFrame>
            <WizardProgressFab />
        </SceneFrame>
    )
}

/** Wizard finished cleanly; green ring + ✓ + dismiss available. */
export const Completed: StoryFn<StoryArgs> = withSession((skillId) =>
    makeSession({
        skill_id: skillId,
        run_phase: 'completed',
        tasks: buildTasks(['completed', 'completed', 'completed', 'completed', 'completed']),
    })
)

/** Wizard errored; red ring + ✗ + dismiss available. */
export const Errored: StoryFn<StoryArgs> = withSession((skillId) =>
    makeSession({
        skill_id: skillId,
        run_phase: 'error',
        tasks: buildTasks(['completed', 'completed', 'failed', 'canceled', 'canceled']),
        error: { type: 'TimeoutError', message: 'Anthropic API timed out' },
    })
)

/**
 * Auto-playing run that mirrors the real-world timeline. Watch the ring fill, the
 * shimmer rainbow underneath, and the sub-line update with each task transition.
 *
 *   t=0s   session opens (Analyzing — indeterminate ring spin)
 *   t=4s   task 1 in_progress
 *   t=8s   task 1 ✓, task 2 in_progress
 *   t=12s  task 2 ✓, task 3 in_progress
 *   t=16s  task 3 ✓, task 4 in_progress
 *   t=20s  task 4 ✓, task 5 in_progress
 *   t=24s  task 5 ✓, run_phase = completed (green ring + dismiss visible)
 */
export const SimulatedRun: StoryFn<StoryArgs> = function SimulatedRunStory({ skillId }) {
    useMountedLogic(wizardProgressTrackerLogic)
    const streamLogic = wizardSessionStreamLogic({ workflowId: WORKFLOW_ID })
    useMountedLogic(streamLogic)

    const timersRef = useRef<number[]>([])

    useEffect(() => {
        const { actions } = streamLogic
        const startedAt = new Date().toISOString()
        const base: WizardSessionFixture = {
            session_id: `${WORKFLOW_ID}-${skillId}-${startedAt}`,
            team_id: 1,
            workflow_id: WORKFLOW_ID,
            skill_id: skillId,
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
    }, [skillId])

    return (
        <SceneFrame>
            <WizardProgressFab />
        </SceneFrame>
    )
}

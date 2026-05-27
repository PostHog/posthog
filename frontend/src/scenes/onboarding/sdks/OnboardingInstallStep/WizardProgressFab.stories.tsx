import { Meta, StoryFn } from '@storybook/react'
import { useMountedLogic } from 'kea'
import { useEffect } from 'react'

import { wizardSessionStreamLogic } from 'products/wizard/frontend/wizardSessionStreamLogic'

import { WizardProgressFab } from './WizardProgressFab'
import { wizardProgressTrackerLogic } from './wizardProgressTrackerLogic'

const WORKFLOW_ID = 'posthog-integration'
const SKILL_ID = 'laravel'

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
            // eslint-disable-next-line react-hooks/exhaustive-deps
        }, [])

        return (
            <SceneFrame>
                <WizardProgressFab />
            </SceneFrame>
        )
    }
}

const meta: Meta = {
    title: 'Scenes-Other/Onboarding/Wizard Progress FAB',
    component: WizardProgressFab,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
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
                    onboarding flow until the wizard finishes.
                </p>
            </div>
            {children}
        </div>
    )
}

/** No session — FAB should render nothing. */
export const Hidden: StoryFn = withSession(null)

/** Wizard mid-run; pulsing dot, not dismissible. */
export const Running: StoryFn = withSession(
    makeSession({
        run_phase: 'running',
    })
)

/** Reconnecting state — same visual treatment as running. */
export const Connecting: StoryFn = withSession(
    makeSession({
        run_phase: 'running',
    })
)

/** Wizard finished cleanly; success colour + dismissible. */
export const Completed: StoryFn = withSession(
    makeSession({
        run_phase: 'completed',
    })
)

/** Wizard errored; brand-red FAB + dismissible. */
export const Errored: StoryFn = withSession(
    makeSession({
        run_phase: 'error',
        error: { type: 'TimeoutError', message: 'Anthropic API timed out' },
    })
)

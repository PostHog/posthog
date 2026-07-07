import { Meta, StoryFn } from '@storybook/react'
import { useMountedLogic } from 'kea'
import { useEffect } from 'react'

import { IconArrowRight, IconCheckCircle } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { Logomark } from 'lib/brand'

import { wizardSessionStreamLogic } from 'products/wizard/frontend/wizardSessionStreamLogic'

import { WizardProgressTracker } from '.'
import { WIZARD_SKILL_IDS } from '../../skillBadge'
import { wizardProgressTrackerLogic } from '../wizardProgressTrackerLogic'

const WORKFLOW_ID = 'posthog-integration'
const DEFAULT_SKILL_ID = 'laravel'

/** Every framework the wizard CLI ships, plus a sentinel for the unknown-skill fallback. */
const SKILL_OPTIONS: string[] = [...WIZARD_SKILL_IDS, 'unknown-skill']

interface StoryArgs {
    skillId: string
}

/**
 * Run phase override for the full-scene story. `connecting` is a derived UI
 * state (session is `running` + transport errored) — the rest map 1:1 to the
 * session's `run_phase` field.
 */
type RunPhaseArg = 'running' | 'connecting' | 'completed' | 'error'
const RUN_PHASE_OPTIONS: RunPhaseArg[] = ['running', 'connecting', 'completed', 'error']

interface FullSceneArgs extends StoryArgs {
    runPhase: RunPhaseArg
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
        status: 'pending' | 'in_progress' | 'completed' | 'failed' | 'canceled'
    }>
    event_plan: unknown | null
    error: { type: string; message: string } | null
    created_at: string
    updated_at: string
}

function makeSession(overrides: Partial<WizardSessionFixture> = {}): WizardSessionFixture {
    const skill_id = overrides.skill_id ?? DEFAULT_SKILL_ID
    const startedAt = new Date(Date.now() - 30_000).toISOString()
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
                <WizardProgressTracker />
            </SceneFrame>
        )
    }
}

const meta: Meta<StoryArgs> = {
    title: 'Scenes-Other/Onboarding/Wizard Progress Tracker',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
    },
    args: { skillId: DEFAULT_SKILL_ID },
    argTypes: {
        skillId: {
            control: { type: 'select' },
            options: SKILL_OPTIONS,
            description: 'Wizard skill_id — drives the badge logo + display name.',
        },
    },
}
export default meta

function SceneFrame({ children }: { children: React.ReactNode }): JSX.Element {
    return (
        <div className="min-h-screen bg-bg-light text-default px-6 py-10">
            <div className="max-w-4xl mx-auto">
                <h1 className="text-2xl font-bold mb-1">Install</h1>
                <p className="text-muted mb-8">
                    Once the wizard session is observed, this confirmation card replaces the install command block. The
                    live progress lives in the floating FAB.
                </p>
                <div className="max-w-2xl mx-auto">{children}</div>
            </div>
        </div>
    )
}

/** No session yet — tracker renders nothing (parent shows the command block). */
export const PreTakeover: StoryFn<StoryArgs> = withSession(() => null)

/** Live session in flight — AI-toned confirmation with the skill badge. */
export const Running: StoryFn<StoryArgs> = withSession((skillId) =>
    makeSession({ skill_id: skillId, run_phase: 'running' })
)

/** Connection blip while running — same card, sub-line shifts to "restoring connection". */
export const Reconnecting: StoryFn<StoryArgs> = function ReconnectingStory({ skillId }) {
    useMountedLogic(wizardProgressTrackerLogic)
    const streamLogic = wizardSessionStreamLogic({ workflowId: WORKFLOW_ID })
    useMountedLogic(streamLogic)

    useEffect(() => {
        streamLogic.actions.connectionOpened()
        streamLogic.actions.sessionUpdated(
            makeSession({
                skill_id: skillId,
                run_phase: 'running',
            }) as any
        )
        const id = window.setTimeout(() => {
            streamLogic.actions.connectionErrored('EventSource transport error')
        }, 50)
        return () => window.clearTimeout(id)
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [skillId])

    return (
        <SceneFrame>
            <WizardProgressTracker />
        </SceneFrame>
    )
}

/** Run finished cleanly — success card pointing the user at the Continue button. */
export const Completed: StoryFn<StoryArgs> = withSession((skillId) =>
    makeSession({ skill_id: skillId, run_phase: 'completed' })
)

/** Run hit an error — error card with type + message + manual-setup fallback. */
export const Errored: StoryFn<StoryArgs> = withSession((skillId) =>
    makeSession({
        skill_id: skillId,
        run_phase: 'error',
        error: {
            type: 'CompositionError',
            message: 'Could not detect a writable .env file. Re-run from the project root and try again.',
        },
    })
)

/**
 * Full install-step scene with the wizard in error state. Mirrors what the user
 * actually sees in production: PostHog nav at the top, "Install" page title with
 * installation-complete + feature-flag indicators in the actions slot, the error
 * confirmation card, the manual-setup escape hatch, and the Next CTA.
 *
 * Useful for design review — shows the card sized and balanced inside the real
 * install-step chrome rather than floating on a bare page.
 */
export const FullInstallStepWithError: StoryFn<FullSceneArgs> = function FullInstallStepWithErrorStory({
    skillId,
    runPhase,
}) {
    useMountedLogic(wizardProgressTrackerLogic)
    const streamLogic = wizardSessionStreamLogic({ workflowId: WORKFLOW_ID })
    useMountedLogic(streamLogic)

    useEffect(() => {
        streamLogic.actions.connectionOpened()
        // `connecting` is a derived state — the session stays `running` and we drop the
        // transport on the floor to flip the displayState selector.
        const sessionRunPhase = runPhase === 'connecting' ? 'running' : runPhase
        streamLogic.actions.sessionUpdated(
            makeSession({
                skill_id: skillId,
                run_phase: sessionRunPhase,
                error:
                    runPhase === 'error'
                        ? {
                              type: 'wizard_error',
                              message:
                                  'Could not access the setup resource. This may indicate a version mismatch or a temporary service issue. Please try again, or check the documentation: https://posthog.com/docs/libraries/node',
                          }
                        : null,
            }) as any
        )
        if (runPhase === 'connecting') {
            const id = window.setTimeout(() => {
                streamLogic.actions.connectionErrored('EventSource transport error — reconnecting')
            }, 50)
            return () => window.clearTimeout(id)
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [skillId, runPhase])

    return (
        <FullInstallSceneFrame
            stepIndicator={
                <span className="inline-flex items-center gap-1.5 text-success font-semibold">
                    <IconCheckCircle className="text-lg" />
                    <span>Installation complete</span>
                </span>
            }
            secondaryIndicator={
                <div className="px-3 py-1.5 rounded border border-border inline-flex items-center gap-2 text-xs">
                    <span className="w-2 h-2 rounded-full bg-success" aria-hidden />
                    <span className="font-semibold">Feature flag called</span>
                    <span className="text-muted">a few seconds ago</span>
                </div>
            }
        >
            <WizardProgressTracker />
            <div className="mt-6 text-sm">Need to set up manually?</div>
            <div className="mt-12 flex justify-end">
                <LemonButton
                    type="primary"
                    size="medium"
                    sideIcon={<IconArrowRight />}
                    onClick={() => alert('Advance to the next onboarding step')}
                >
                    Next
                </LemonButton>
            </div>
        </FullInstallSceneFrame>
    )
}
FullInstallStepWithError.args = { skillId: 'javascript-node', runPhase: 'error' }
FullInstallStepWithError.argTypes = {
    runPhase: {
        control: { type: 'select' },
        options: RUN_PHASE_OPTIONS,
        description: 'Wizard phase — drives the banner type (ai / success / error) and copy.',
    },
}

/**
 * Faux install-step chrome — nav bar, page title, status indicators, content slot.
 * Not pixel-perfect; just enough scaffolding to evaluate the card's position and
 * rhythm against the rest of the page.
 */
function FullInstallSceneFrame({
    children,
    stepIndicator,
    secondaryIndicator,
}: {
    children: React.ReactNode
    stepIndicator?: React.ReactNode
    secondaryIndicator?: React.ReactNode
}): JSX.Element {
    return (
        <div className="min-h-screen bg-bg-light text-default flex flex-col">
            <div className="border-b border-border bg-bg-light px-6 py-3 flex items-center justify-between">
                <div className="flex items-center gap-2">
                    <span className="inline-flex w-8 h-8 items-center justify-center">
                        <Logomark className="w-8 h-auto" />
                    </span>
                </div>
                <div className="flex items-center gap-4 text-sm">
                    <span className="inline-flex items-center gap-1">
                        <span>Hedgebox</span>
                        <span className="text-muted">▾</span>
                    </span>
                    <span className="inline-flex items-center gap-2">
                        <span className="w-7 h-7 rounded-full bg-purple-300 inline-flex items-center justify-center text-xs font-semibold text-purple-900">
                            J
                        </span>
                        <span>Josh</span>
                    </span>
                </div>
            </div>
            <div className="flex-1 w-full max-w-4xl mx-auto px-6 py-10">
                <div className="flex items-center justify-between gap-4 flex-wrap mb-8">
                    <h1 className="text-3xl font-bold m-0">Install</h1>
                    <div className="flex items-center gap-4 text-sm">
                        {stepIndicator}
                        {secondaryIndicator}
                    </div>
                </div>
                {children}
            </div>
        </div>
    )
}

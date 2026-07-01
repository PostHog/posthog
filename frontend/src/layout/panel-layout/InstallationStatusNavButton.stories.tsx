import type { Meta, StoryObj } from '@storybook/react'
import { useMountedLogic } from 'kea'
import { useEffect } from 'react'

import { wizardActiveSessionDetectorLogic } from 'scenes/onboarding/legacy/sdks/OnboardingInstallStep/wizardActiveSessionDetectorLogic'
import { activeCloudRunLogic } from 'scenes/onboarding/self-driving/sdks/OnboardingInstallStep/activeCloudRunLogic'
import type { CloudRunHandle } from 'scenes/onboarding/self-driving/sdks/OnboardingInstallStep/activeCloudRunLogic'
import { teamLogic } from 'scenes/teamLogic'

import { InstallationStatusNavButton } from './InstallationStatusNavButton'
import { installationStatusNavLogic } from './installationStatusNavLogic'

type Story = StoryObj<typeof InstallationStatusNavButton>

const meta: Meta<typeof InstallationStatusNavButton> = {
    title: 'Layout/Nav Bar/Installation Status',
    component: InstallationStatusNavButton,
    parameters: {
        layout: 'padded',
        viewMode: 'story',
        featureFlags: [{ 'onboarding-wizard-sidebar': 'test' }],
        // The active-session detector polls `sessions/latest/` after randomized jitter.
        // Without a handler the test-runner's `networkidle` wait never settles.
        msw: {
            mocks: {
                get: {
                    '/api/projects/:projectId/wizard/sessions/latest/': () => [204, ''],
                },
            },
        },
        mockDate: '2024-05-01 12:00:00',
    },
    decorators: [
        (Story) => (
            <div className="w-[240px] bg-surface-primary rounded border border-primary overflow-hidden">
                <div className="p-2 border-b border-primary text-xs text-muted uppercase tracking-wide">Sidebar</div>
                <div className="p-1 flex flex-col gap-px">
                    <Story />
                </div>
            </div>
        ),
    ],
    args: {
        iconOnly: false,
    },
    argTypes: {
        iconOnly: { control: 'boolean' },
    },
}

export default meta

// ── Helpers ──────────────────────────────────────────────────────────────────

function makeCloudRunHandle(overrides?: Partial<CloudRunHandle>): CloudRunHandle {
    const startedAt = new Date(Date.now() - 134_000).toISOString()
    return {
        taskId: 'task-abc',
        runId: 'run-xyz',
        startedAt,
        ...overrides,
    }
}

/**
 * Sets up the team as fully onboarded (no onboarding needed). Use as a baseline for stories that
 * rely on a run being the only reason for showing.
 */
function setupTeamOnboarded(): void {
    useEffect(() => {
        teamLogic.actions.loadCurrentTeamSuccess({
            id: 1,
            name: 'Test Team',
            completed_snippet_onboarding: true,
            has_completed_onboarding_for: { product_analytics: true },
            ingested_event: true,
            is_demo: false,
        } as any)
    }, [])
}

/**
 * Sets up the team as not yet onboarded — no events ingested, no product completed. This is the
 * "incomplete onboarding" state.
 */
function setupTeamNotOnboarded(): void {
    useEffect(() => {
        teamLogic.actions.loadCurrentTeamSuccess({
            id: 1,
            name: 'Test Team',
            completed_snippet_onboarding: false,
            has_completed_onboarding_for: {},
            ingested_event: false,
            is_demo: false,
        } as any)
    }, [])
}

/**
 * Simulates an active cloud run by writing a handle to activeCloudRunLogic.
 */
function setupCloudRun(overrides?: Partial<CloudRunHandle>): void {
    useEffect(() => {
        const handle = makeCloudRunHandle(overrides)
        activeCloudRunLogic.actions.setActiveCloudRun(handle.taskId, handle.runId, handle.startedAt!)
    }, [overrides])
}

/**
 * Simulates an active local wizard session via the detector logic.
 */
function setupLocalSession(): void {
    useEffect(() => {
        wizardActiveSessionDetectorLogic.actions.markActive()
    }, [])
}

// ── Stories ──────────────────────────────────────────────────────────────────

/** Flag is off — the component does not render. */
export const FlagOff: Story = {
    parameters: {
        featureFlags: [], // no 'onboarding-wizard-sidebar'
    },
    decorators: [
        (Story) => {
            setupTeamNotOnboarded()
            return <Story />
        },
    ],
}

/** User is fully onboarded and there is no active run — nothing to show. */
export const Hidden: Story = {
    decorators: [
        (Story) => {
            setupTeamOnboarded()
            return (
                <>
                    <Story />
                </>
            )
        },
    ],
}

/** User hasn't completed onboarding — muted "Complete setup" dot. */
export const IncompleteOnboarding: Story = {
    decorators: [
        (Story) => {
            setupTeamNotOnboarded()
            return <Story />
        },
    ],
}

/** Cloud run in progress — pulsing accent dot, elapsed time. */
export const CloudRunInProgress: Story = {
    decorators: [
        (Story) => {
            setupTeamOnboarded()
            setupCloudRun({
                startedAt: new Date(Date.now() - 60_000).toISOString(),
            })
            return <Story />
        },
    ],
}

/** Local wizard session detected — pulsing accent dot. */
export const LocalSessionActive: Story = {
    decorators: [
        (Story) => {
            useMountedLogic(installationStatusNavLogic)
            setupTeamOnboarded()
            setupLocalSession()
            return <Story />
        },
    ],
}

/** Collapsed sidebar — iconOnly mode. */
export const CollapsedNav: Story = {
    args: {
        iconOnly: true,
    },
    decorators: [
        (Story) => {
            setupTeamNotOnboarded()
            return <Story />
        },
    ],
}

/** Collapsed nav with a cloud run in progress. */
export const CollapsedNavCloudRun: Story = {
    args: {
        iconOnly: true,
    },
    decorators: [
        (Story) => {
            setupTeamOnboarded()
            setupCloudRun({
                startedAt: new Date(Date.now() - 60_000).toISOString(),
            })
            return <Story />
        },
    ],
}

// ── Gallery ──────────────────────────────────────────────────────────────────

/** Every state in one frame for side-by-side review. */
export const AllStates: Story = {
    parameters: { controls: { disable: true } },
    render: () => {
        // Each variant wraps a copy of the button with its own logic setup via decorator-style mounts.
        function StateBlock({ label, children }: { label: string; children: React.ReactNode }): JSX.Element {
            return (
                <div className="flex flex-col gap-1">
                    <span className="text-xs text-muted">{label}</span>
                    <div className="w-[240px] bg-surface-primary rounded border border-primary overflow-hidden">
                        <div className="p-2 border-b border-primary text-xs text-muted uppercase tracking-wide">
                            Sidebar
                        </div>
                        <div className="p-1 flex flex-col gap-px">{children}</div>
                    </div>
                </div>
            )
        }

        return (
            <div className="flex flex-col gap-4">
                <StateBlock label="Hidden (onboarded)">
                    <TeamOnboardedWrapper />
                </StateBlock>
                <StateBlock label="Incomplete onboarding">
                    <TeamNotOnboardedWrapper iconOnly={false} />
                </StateBlock>
                <StateBlock label="Cloud run in progress">
                    <CloudRunWrapper iconOnly={false} startedAtOffset={60_000} />
                </StateBlock>
                <StateBlock label="Local session active">
                    <LocalSessionWrapper iconOnly={false} />
                </StateBlock>
                <StateBlock label="Collapsed (incomplete)">
                    <TeamNotOnboardedWrapper iconOnly={true} />
                </StateBlock>
                <StateBlock label="Collapsed (cloud run)">
                    <CloudRunWrapper iconOnly={true} startedAtOffset={60_000} />
                </StateBlock>
            </div>
        )
    },
}

/** Wraps the button with team set to fully onboarded (no run active → hidden). */
function TeamOnboardedWrapper(): JSX.Element {
    useMountedLogic(installationStatusNavLogic)
    setupTeamOnboarded_Inline()
    return <InstallationStatusNavButton iconOnly={false} />
}

/** Wraps the button with team not onboarded. */
function TeamNotOnboardedWrapper({ iconOnly }: { iconOnly: boolean }): JSX.Element {
    useMountedLogic(installationStatusNavLogic)
    setupTeamNotOnboarded_Inline()
    return <InstallationStatusNavButton iconOnly={iconOnly} />
}

/** Wraps the button with a cloud run in progress. */
function CloudRunWrapper({ iconOnly, startedAtOffset }: { iconOnly: boolean; startedAtOffset: number }): JSX.Element {
    useMountedLogic(installationStatusNavLogic)
    setupTeamOnboarded_Inline()
    setupCloudRun_Inline({ startedAt: new Date(Date.now() - startedAtOffset).toISOString() })
    return <InstallationStatusNavButton iconOnly={iconOnly} />
}

/** Wraps the button with a local session active. */
function LocalSessionWrapper({ iconOnly }: { iconOnly: boolean }): JSX.Element {
    useMountedLogic(installationStatusNavLogic)
    setupTeamOnboarded_Inline()
    setupLocalSession_Inline()
    return <InstallationStatusNavButton iconOnly={iconOnly} />
}

// Inline (non-hook) versions of the setup functions for use in render callbacks.
// In a render callback we cannot use hooks, so these dispatch actions directly via mount-time effects.
function setupTeamOnboarded_Inline(): void {
    useMountedLogic(teamLogic)
    useEffect(() => {
        teamLogic.actions.loadCurrentTeamSuccess({
            id: 1,
            name: 'Test Team',
            completed_snippet_onboarding: true,
            has_completed_onboarding_for: { product_analytics: true },
            ingested_event: true,
            is_demo: false,
        } as any)
    }, [])
}

function setupTeamNotOnboarded_Inline(): void {
    useMountedLogic(teamLogic)
    useEffect(() => {
        teamLogic.actions.loadCurrentTeamSuccess({
            id: 1,
            name: 'Test Team',
            completed_snippet_onboarding: false,
            has_completed_onboarding_for: {},
            ingested_event: false,
            is_demo: false,
        } as any)
    }, [])
}

function setupCloudRun_Inline(overrides?: Partial<CloudRunHandle>): void {
    useMountedLogic(activeCloudRunLogic)
    useEffect(() => {
        const handle = makeCloudRunHandle(overrides)
        activeCloudRunLogic.actions.setActiveCloudRun(handle.taskId, handle.runId, handle.startedAt!)
    }, [overrides])
}

function setupLocalSession_Inline(): void {
    useMountedLogic(wizardActiveSessionDetectorLogic)
    useEffect(() => {
        wizardActiveSessionDetectorLogic.actions.markActive()
    }, [])
}

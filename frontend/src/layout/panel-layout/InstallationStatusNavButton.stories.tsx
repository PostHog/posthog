import { MOCK_TEAM_ID } from 'lib/api.mock'

import type { Meta, StoryObj } from '@storybook/react'
import { useMountedLogic } from 'kea'
import { useEffect } from 'react'

import { wizardActiveSessionDetectorLogic } from 'scenes/onboarding/legacy/sdks/OnboardingInstallStep/wizardActiveSessionDetectorLogic'
import {
    activeCloudRunLogic,
    type CloudRunHandle,
} from 'scenes/onboarding/self-driving/sdks/OnboardingInstallStep/activeCloudRunLogic'
import { projectLogic } from 'scenes/projectLogic'
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

/** Hook: sets the team as fully onboarded. */
function useTeamOnboarded(): void {
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

/** Hook: sets the team as not yet onboarded. */
function useTeamNotOnboarded(): void {
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

/** Hook: simulates an active cloud run. */
function useCloudRun(overrides?: Partial<CloudRunHandle>): void {
    useMountedLogic(activeCloudRunLogic)
    useEffect(() => {
        const handle = makeCloudRunHandle(overrides)
        // The handle is project-scoped; stamp whichever project the storybook environment resolves.
        activeCloudRunLogic.actions.setActiveCloudRun(
            handle.taskId,
            handle.runId,
            handle.startedAt!,
            projectLogic.values.currentProjectId ?? MOCK_TEAM_ID
        )
    }, [overrides])
}

/** Hook: simulates an active local wizard session. */
function useLocalSession(): void {
    useMountedLogic(wizardActiveSessionDetectorLogic)
    useEffect(() => {
        wizardActiveSessionDetectorLogic.actions.markActive()
    }, [])
}

// ── Stories ──────────────────────────────────────────────────────────────────

/** Flag is off — the component does not render. */
export const FlagOff: Story = {
    parameters: {
        featureFlags: [],
    },
    decorators: [
        (Story) => {
            useTeamNotOnboarded()
            return <Story />
        },
    ],
}

/** User is fully onboarded and there is no active run — nothing to show. */
export const Hidden: Story = {
    decorators: [
        (Story) => {
            useTeamOnboarded()
            return <Story />
        },
    ],
}

/** User hasn't completed onboarding — muted "Complete setup" dot. */
export const IncompleteOnboarding: Story = {
    decorators: [
        (Story) => {
            useTeamNotOnboarded()
            return <Story />
        },
    ],
}

/** Cloud run in progress — pulsing accent dot, elapsed time. */
export const CloudRunInProgress: Story = {
    decorators: [
        (Story) => {
            useTeamOnboarded()
            useCloudRun({ startedAt: new Date(Date.now() - 60_000).toISOString() })
            return <Story />
        },
    ],
}

/** Local wizard session detected — pulsing accent dot. */
export const LocalSessionActive: Story = {
    decorators: [
        (Story) => {
            useMountedLogic(installationStatusNavLogic)
            useTeamOnboarded()
            useLocalSession()
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
            useTeamNotOnboarded()
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
            useTeamOnboarded()
            useCloudRun({ startedAt: new Date(Date.now() - 60_000).toISOString() })
            return <Story />
        },
    ],
}

// ── Gallery ──────────────────────────────────────────────────────────────────

function StateBlock({ label, children }: { label: string; children: React.ReactNode }): JSX.Element {
    return (
        <div className="flex flex-col gap-1">
            <span className="text-xs text-muted">{label}</span>
            <div className="w-[240px] bg-surface-primary rounded border border-primary overflow-hidden">
                <div className="p-2 border-b border-primary text-xs text-muted uppercase tracking-wide">Sidebar</div>
                <div className="p-1 flex flex-col gap-px">{children}</div>
            </div>
        </div>
    )
}

/** Wraps the button with team set to fully onboarded (no run active → hidden). */
function OnboardedVariant(): JSX.Element {
    useMountedLogic(installationStatusNavLogic)
    useTeamOnboarded()
    return <InstallationStatusNavButton iconOnly={false} />
}

/** Wraps the button with team not onboarded. */
function NotOnboardedVariant({ iconOnly }: { iconOnly: boolean }): JSX.Element {
    useMountedLogic(installationStatusNavLogic)
    useTeamNotOnboarded()
    return <InstallationStatusNavButton iconOnly={iconOnly} />
}

/** Wraps the button with a cloud run in progress. */
function CloudRunVariant({ iconOnly, startedAtOffset }: { iconOnly: boolean; startedAtOffset: number }): JSX.Element {
    useMountedLogic(installationStatusNavLogic)
    useTeamOnboarded()
    useCloudRun({ startedAt: new Date(Date.now() - startedAtOffset).toISOString() })
    return <InstallationStatusNavButton iconOnly={iconOnly} />
}

/** Wraps the button with a local session active. */
function LocalSessionVariant({ iconOnly }: { iconOnly: boolean }): JSX.Element {
    useMountedLogic(installationStatusNavLogic)
    useTeamOnboarded()
    useLocalSession()
    return <InstallationStatusNavButton iconOnly={iconOnly} />
}

/** Every state in one frame for side-by-side review. */
export const AllStates: Story = {
    parameters: { controls: { disable: true } },
    render: () => (
        <div className="flex flex-col gap-4">
            <StateBlock label="Hidden (onboarded)">
                <OnboardedVariant />
            </StateBlock>
            <StateBlock label="Incomplete onboarding">
                <NotOnboardedVariant iconOnly={false} />
            </StateBlock>
            <StateBlock label="Cloud run in progress">
                <CloudRunVariant iconOnly={false} startedAtOffset={60_000} />
            </StateBlock>
            <StateBlock label="Local session active">
                <LocalSessionVariant iconOnly={false} />
            </StateBlock>
            <StateBlock label="Collapsed (incomplete)">
                <NotOnboardedVariant iconOnly={true} />
            </StateBlock>
            <StateBlock label="Collapsed (cloud run)">
                <CloudRunVariant iconOnly={true} startedAtOffset={60_000} />
            </StateBlock>
        </div>
    ),
}

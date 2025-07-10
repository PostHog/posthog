import type { Meta, StoryObj } from '@storybook/react'
import { Provider } from 'kea'
import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'
import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { TeamType } from '~/types'

import { FeatureFlagSettings } from './FeatureFlagSettings'

type Story = StoryObj<typeof FeatureFlagSettings>

const meta: Meta<typeof FeatureFlagSettings> = {
    title: 'Scenes-App/Feature Flags/FeatureFlagSettings',
    component: FeatureFlagSettings,
    parameters: {
        layout: 'padded',
        viewMode: 'story',
    },
    tags: ['autodocs'],
}

export default meta

// Helper to setup common test environment
const setupTestEnvironment = (teamOverrides: Partial<TeamType> = {}): TeamType => {
    initKeaTests()

    const team: TeamType = {
        ...MOCK_DEFAULT_TEAM,
        ...teamOverrides,
    }

    useMocks({
        patch: {
            '/api/projects/:id': async (req, res, ctx) => {
                const updatedTeam = { ...team, ...(await req.json()) }
                return res(ctx.json(updatedTeam))
            },
        },
    })

    // Load team data
    teamLogic.actions.loadCurrentTeamSuccess(team)

    return team
}

// Helper to wrap stories with proper Kea context
const Template = (teamOverrides: Partial<TeamType> = {}): JSX.Element => {
    setupTestEnvironment(teamOverrides)

    return (
        <Provider>
            <div className="max-w-4xl">
                <FeatureFlagSettings />
            </div>
        </Provider>
    )
}

export const Default: Story = {
    render: () => Template(),
}

export const ConfirmationEnabled: Story = {
    render: () =>
        Template({
            feature_flag_confirmation_enabled: true,
        }),
}

export const ConfirmationEnabledWithCustomMessage: Story = {
    render: () =>
        Template({
            feature_flag_confirmation_enabled: true,
            feature_flag_confirmation_message:
                'Please double-check your changes as they will affect live users in production.',
        }),
}

export const ConfirmationEnabledWithLongMessage: Story = {
    render: () =>
        Template({
            feature_flag_confirmation_enabled: true,
            feature_flag_confirmation_message:
                "This is a very long custom confirmation message that demonstrates how the text area handles longer content. Please carefully review all changes to feature flags as they can have significant impact on your users' experience and may affect critical business flows.",
        }),
}

export const ConfirmationDisabled: Story = {
    render: () =>
        Template({
            feature_flag_confirmation_enabled: false,
            feature_flag_confirmation_message: 'This message should not be visible when confirmation is disabled',
        }),
}

export const InModal: Story = {
    render: () => (
        <Provider>
            <div className="max-w-2xl bg-bg-3000 border border-border rounded p-6">
                <h2 className="text-lg font-semibold mb-4">Feature Flag Settings (Modal)</h2>
                <FeatureFlagSettings inModal />
            </div>
        </Provider>
    ),
    parameters: {
        docs: {
            description: {
                story: 'Settings component as it appears in a modal dialog with different styling.',
            },
        },
    },
}

export const InModalWithConfirmation: Story = {
    render: () => {
        // Use shared setup logic
        setupTestEnvironment({
            feature_flag_confirmation_enabled: true,
            feature_flag_confirmation_message: 'Custom modal confirmation message',
        })

        return (
            <Provider>
                <div className="max-w-2xl bg-bg-3000 border border-border rounded p-6">
                    <h2 className="text-lg font-semibold mb-4">Feature Flag Settings (Modal)</h2>
                    <FeatureFlagSettings inModal />
                </div>
            </Provider>
        )
    },
    parameters: {
        docs: {
            description: {
                story: 'Modal version with confirmation enabled and custom message.',
            },
        },
    },
}

export const Loading: Story = {
    render: () => {
        initKeaTests()

        // Don't load team data to simulate loading state
        useMocks({
            patch: {
                '/api/projects/:id': async (req, res, ctx) => {
                    // Simulate slow response
                    await new Promise((resolve) => setTimeout(resolve, 1000))
                    const requestData = await req.json()
                    return res(ctx.json({ ...MOCK_DEFAULT_TEAM, ...requestData }))
                },
            },
        })

        return (
            <Provider>
                <div className="max-w-4xl">
                    <FeatureFlagSettings />
                </div>
            </Provider>
        )
    },
    parameters: {
        docs: {
            description: {
                story: 'Settings component in loading state when team data is not yet available.',
            },
        },
    },
}

export const InteractiveDemo: Story = {
    render: () =>
        Template({
            feature_flag_confirmation_enabled: true,
            feature_flag_confirmation_message: 'Click the toggle and edit this message to see how the form works!',
        }),
    parameters: {
        docs: {
            description: {
                story: 'Interactive demo where you can toggle settings and edit the confirmation message to see all states.',
            },
        },
    },
}

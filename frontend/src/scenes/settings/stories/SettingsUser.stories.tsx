import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_TEAM, MOCK_DEFAULT_USER } from 'lib/api.mock'

import type { Meta, StoryObj } from '@storybook/react'
import { within } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'
import { router } from 'kea-router'

import { STORYBOOK_FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { getAvailableProductFeatures } from '~/mocks/features'
import preflightJson from '~/mocks/fixtures/_preflight.json'
import { HedgehogConfig } from '~/types'

import { SettingSectionId } from '../types'

interface StoryProps {
    sectionId: SettingSectionId
}

type Story = StoryObj<StoryProps>
const meta: Meta<StoryProps> = {
    title: 'Scenes-App/Settings/User',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-05-25',
        featureFlags: STORYBOOK_FEATURE_FLAGS,
    },
    decorators: [
        mswDecorator({
            get: {
                '/_preflight': {
                    ...preflightJson,
                    cloud: true,
                    realm: 'cloud',
                },
                '/api/projects/:id/integrations': { results: [] },
                '/api/users/@me/login_sessions/': [
                    {
                        id: '0190a1b2-0000-7000-8000-000000000001',
                        device: 'Chrome 113 on Mac OS X 13.4',
                        location: 'San Francisco, United States',
                        login_method: 'password',
                        created_at: '2023-05-20T10:00:00Z',
                        last_activity: '2023-05-25T09:00:00Z',
                        is_current: true,
                    },
                    {
                        id: '0190a1b2-0000-7000-8000-000000000002',
                        device: 'Firefox 113 on Windows 11',
                        location: 'London, United Kingdom',
                        login_method: 'google-oauth2',
                        created_at: '2023-05-10T10:00:00Z',
                        last_activity: '2023-05-24T09:00:00Z',
                        is_current: false,
                    },
                ],
            },
            patch: {
                '/api/projects/:id': async ({ request }) => {
                    // bounce the setting back as is
                    const newTeamSettings = { ...MOCK_DEFAULT_TEAM, ...((await request.json()) as object) }
                    return [200, newTeamSettings]
                },
            },
        }),
    ],
    render: ({ sectionId }) => {
        // Navigate synchronously before <App /> mounts so it renders the settings scene directly,
        // never the project homepage. A useEffect push fires after the first paint, so the snapshot
        // can race and capture the homepage frame instead.
        router.actions.push(urls.settings(sectionId))

        return <App />
    },
}
export default meta

// -- User --

export const SettingsUserProfile: Story = {
    args: { sectionId: 'user-profile' },
}

const HEDGEHOG_AVATAR_CONFIG: HedgehogConfig = {
    version: 2,
    enabled: false,
    use_as_profile: true,
    party_mode_enabled: false,
    actor_options: { id: 'storybook-hedgehog', skin: 'default', color: 'green', accessories: ['tophat', 'sunglasses'] },
}

export const SettingsUserProfileHedgehogAvatar: Story = {
    args: { sectionId: 'user-profile' },
    parameters: {
        msw: {
            mocks: {
                get: {
                    '/api/users/@me/': () => [
                        200,
                        {
                            ...MOCK_DEFAULT_USER,
                            organization: {
                                ...MOCK_DEFAULT_ORGANIZATION,
                                available_product_features: getAvailableProductFeatures(),
                            },
                            hedgehog_config: HEDGEHOG_AVATAR_CONFIG,
                        },
                    ],
                },
            },
        },
    },
}

export const SettingsUserApiKeys: Story = {
    args: { sectionId: 'user-api-keys' },
}

export const SettingsUserNotifications: Story = {
    args: { sectionId: 'user-notifications' },
}

export const SettingsUserCustomization: Story = {
    args: { sectionId: 'user-customization' },
}

export const SettingsUserNavigation: Story = {
    args: { sectionId: 'user-navigation' },
}

export const SettingsUserDangerZone: Story = {
    args: { sectionId: 'user-danger-zone' },
}

export const SettingsUserRemindersModal: Story = {
    args: { sectionId: 'user-reminders' },
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        await userEvent.click(await canvas.findByText('New reminder'))
    },
}

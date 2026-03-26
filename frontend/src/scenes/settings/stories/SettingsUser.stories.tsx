import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import type { Meta, StoryObj } from '@storybook/react'
import { router } from 'kea-router'
import { useEffect } from 'react'

import { STORYBOOK_FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import preflightJson from '~/mocks/fixtures/_preflight.json'

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
            },
            patch: {
                '/api/projects/:id': async (req, res, ctx) => {
                    // bounce the setting back as is
                    const newTeamSettings = { ...MOCK_DEFAULT_TEAM, ...(await req.json()) }
                    return res(ctx.json(newTeamSettings))
                },
            },
        }),
    ],
    render: ({ sectionId }) => {
        useEffect(() => {
            router.actions.push(urls.settings(sectionId))
        }, [sectionId])

        return <App />
    },
}
export default meta

// -- User --

export const SettingsUserProfile: Story = {
    args: { sectionId: 'user-profile' },
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

export const SettingsUserDangerZone: Story = {
    args: { sectionId: 'user-danger-zone' },
}

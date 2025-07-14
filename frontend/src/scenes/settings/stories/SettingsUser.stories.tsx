import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { router } from 'kea-router'
import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'
import { FEATURE_FLAGS } from 'lib/constants'
import { useEffect } from 'react'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import preflightJson from '~/mocks/fixtures/_preflight.json'

import { SettingSectionId } from '../types'

interface StoryProps {
    sectionId: SettingSectionId
}

type Story = StoryObj<(props: StoryProps) => JSX.Element>
const meta: Meta<(props: StoryProps) => JSX.Element> = {
    title: 'Scenes-App/Settings/User',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-05-25',
        featureFlags: Object.values(FEATURE_FLAGS), // Enable all feature flags for the settings page
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
}
export default meta

const Template: StoryFn<StoryProps> = ({ sectionId }) => {
    useEffect(() => {
        router.actions.push(urls.settings(sectionId))
    }, [sectionId])

    return <App />
}

// -- User --

export const SettingsUserProfile: Story = Template.bind({})
SettingsUserProfile.args = { sectionId: 'user-profile' }

export const SettingsUserApiKeys: Story = Template.bind({})
SettingsUserApiKeys.args = { sectionId: 'user-api-keys' }

export const SettingsUserNotifications: Story = Template.bind({})
SettingsUserNotifications.args = { sectionId: 'user-notifications' }

export const SettingsUserCustomization: Story = Template.bind({})
SettingsUserCustomization.args = { sectionId: 'user-customization' }

export const SettingsUserDangerZone: Story = Template.bind({})
SettingsUserDangerZone.args = { sectionId: 'user-danger-zone' }

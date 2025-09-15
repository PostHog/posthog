import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { router } from 'kea-router'
import { useEffect } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
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
    title: 'Scenes-App/Settings/Organization',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-05-25',
        featureFlags: Object.values(FEATURE_FLAGS),
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

// -- Organization --

export const SettingsOrganizationDetails: Story = Template.bind({})
SettingsOrganizationDetails.args = { sectionId: 'organization-details' }

export const SettingsOrganizationMembers: Story = Template.bind({})
SettingsOrganizationMembers.args = { sectionId: 'organization-members' }

export const SettingsOrganizationRoles: Story = Template.bind({})
SettingsOrganizationRoles.args = { sectionId: 'organization-roles' }

export const SettingsOrganizationAuthentication: Story = Template.bind({})
SettingsOrganizationAuthentication.args = { sectionId: 'organization-authentication' }

export const SettingsOrganizationProxy: Story = Template.bind({})
SettingsOrganizationProxy.args = { sectionId: 'organization-proxy' }

export const SettingsOrganizationDangerZone: Story = Template.bind({})
SettingsOrganizationDangerZone.args = { sectionId: 'organization-danger-zone' }

export const SettingsOrganizationBilling: Story = Template.bind({})
SettingsOrganizationBilling.args = { sectionId: 'organization-billing' }

export const SettingsOrganizationStartupProgram: Story = Template.bind({})
SettingsOrganizationStartupProgram.args = { sectionId: 'organization-startup-program' }

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
    title: 'Scenes-App/Settings/Project',
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

// -- Project --

export const SettingsProjectDetails: Story = Template.bind({})
SettingsProjectDetails.args = { sectionId: 'project-details' }

export const SettingsProjectDangerZone: Story = Template.bind({})
SettingsProjectDangerZone.args = { sectionId: 'project-danger-zone' }

// -- Project (legacy) --

export const SettingsProjectAutocapture: Story = Template.bind({})
SettingsProjectAutocapture.args = { sectionId: 'project-autocapture' }

export const SettingsProjectProductAnalytics: Story = Template.bind({})
SettingsProjectProductAnalytics.args = { sectionId: 'project-product-analytics' }

export const SettingsProjectReplay: Story = Template.bind({})
SettingsProjectReplay.args = { sectionId: 'project-replay' }

export const SettingsProjectSurveys: Story = Template.bind({})
SettingsProjectSurveys.args = { sectionId: 'project-surveys' }

export const SettingsProjectIntegrations: Story = Template.bind({})
SettingsProjectIntegrations.args = { sectionId: 'project-integrations' }

export const SettingsProjectAccessControl: Story = Template.bind({})
SettingsProjectAccessControl.args = { sectionId: 'project-access-control' }

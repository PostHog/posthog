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
    title: 'Scenes-App/Settings/Environment',
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

// -- Environment --
export const SettingsEnvironmentDetails: Story = Template.bind({})
SettingsEnvironmentDetails.args = { sectionId: 'environment-details' }

export const SettingsEnvironmentAutocapture: Story = Template.bind({})
SettingsEnvironmentAutocapture.args = { sectionId: 'environment-autocapture' }

export const SettingsEnvironmentProductAnalytics: Story = Template.bind({})
SettingsEnvironmentProductAnalytics.args = { sectionId: 'environment-product-analytics' }

export const SettingsEnvironmentRevenueAnalytics: Story = Template.bind({})
SettingsEnvironmentRevenueAnalytics.args = { sectionId: 'environment-revenue-analytics' }

export const SettingsEnvironmentMarketingAnalytics: Story = Template.bind({})
SettingsEnvironmentMarketingAnalytics.args = { sectionId: 'environment-marketing-analytics' }

export const SettingsEnvironmentWebAnalytics: Story = Template.bind({})
SettingsEnvironmentWebAnalytics.args = { sectionId: 'environment-web-analytics' }

export const SettingsEnvironmentReplay: Story = Template.bind({})
SettingsEnvironmentReplay.args = { sectionId: 'environment-replay' }

export const SettingsEnvironmentSurveys: Story = Template.bind({})
SettingsEnvironmentSurveys.args = { sectionId: 'environment-surveys' }

export const SettingsEnvironmentFeatureFlags: Story = Template.bind({})
SettingsEnvironmentFeatureFlags.args = { sectionId: 'environment-feature-flags' }

export const SettingsEnvironmentErrorTracking: Story = Template.bind({})
SettingsEnvironmentErrorTracking.args = { sectionId: 'environment-error-tracking' }

export const SettingsEnvironmentCSPReporting: Story = Template.bind({})
SettingsEnvironmentCSPReporting.args = { sectionId: 'environment-csp-reporting' }

export const SettingsEnvironmentMax: Story = Template.bind({})
SettingsEnvironmentMax.args = { sectionId: 'environment-max' }

export const SettingsEnvironmentIntegrations: Story = Template.bind({})
SettingsEnvironmentIntegrations.args = { sectionId: 'environment-integrations' }

export const SettingsEnvironmentAccessControl: Story = Template.bind({})
SettingsEnvironmentAccessControl.args = { sectionId: 'environment-access-control' }

export const SettingsEnvironmentDangerZone: Story = Template.bind({})
SettingsEnvironmentDangerZone.args = { sectionId: 'environment-danger-zone' }

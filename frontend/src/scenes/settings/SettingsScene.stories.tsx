import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { router } from 'kea-router'
import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'
import { FEATURE_FLAGS } from 'lib/constants'
import { useEffect } from 'react'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import preflightJson from '~/mocks/fixtures/_preflight.json'

import { SettingSectionId } from './types'

interface StoryProps {
    sectionId: SettingSectionId
}

type Story = StoryObj<(props: StoryProps) => JSX.Element>
const meta: Meta<(props: StoryProps) => JSX.Element> = {
    title: 'Scenes-App/Settings',
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

// NOTE: This is used to guarantee we're testing all sections
const _ALL_SECTIONS_CHECKER: Record<SettingSectionId, Story> = {
    'environment-details': SettingsEnvironmentDetails,
    'environment-autocapture': SettingsEnvironmentAutocapture,
    'environment-product-analytics': SettingsEnvironmentProductAnalytics,
    'environment-revenue-analytics': SettingsEnvironmentRevenueAnalytics,
    'environment-marketing-analytics': SettingsEnvironmentMarketingAnalytics,
    'environment-web-analytics': SettingsEnvironmentWebAnalytics,
    'environment-replay': SettingsEnvironmentReplay,
    'environment-surveys': SettingsEnvironmentSurveys,
    'environment-feature-flags': SettingsEnvironmentFeatureFlags,
    'environment-error-tracking': SettingsEnvironmentErrorTracking,
    'environment-csp-reporting': SettingsEnvironmentCSPReporting,
    'environment-max': SettingsEnvironmentMax,
    'environment-integrations': SettingsEnvironmentIntegrations,
    'environment-access-control': SettingsEnvironmentAccessControl,
    'environment-danger-zone': SettingsEnvironmentDangerZone,
    'project-details': SettingsProjectDetails,
    'project-danger-zone': SettingsProjectDangerZone,
    'project-autocapture': SettingsProjectAutocapture,
    'project-product-analytics': SettingsProjectProductAnalytics,
    'project-replay': SettingsProjectReplay,
    'project-surveys': SettingsProjectSurveys,
    'project-integrations': SettingsProjectIntegrations,
    'project-access-control': SettingsProjectAccessControl,
    'organization-details': SettingsOrganizationDetails,
    'organization-members': SettingsOrganizationMembers,
    'organization-roles': SettingsOrganizationRoles,
    'organization-authentication': SettingsOrganizationAuthentication,
    'organization-proxy': SettingsOrganizationProxy,
    'organization-danger-zone': SettingsOrganizationDangerZone,
    'organization-billing': SettingsOrganizationBilling,
    'organization-startup-program': SettingsOrganizationStartupProgram,
    'user-profile': SettingsUserProfile,
    'user-api-keys': SettingsUserApiKeys,
    'user-notifications': SettingsUserNotifications,
    'user-customization': SettingsUserCustomization,
    'user-danger-zone': SettingsUserDangerZone,
}

// NOTE: This is here to avoid TS complaining
// about us not using the variable used above to check all sections
;(() => _ALL_SECTIONS_CHECKER)()

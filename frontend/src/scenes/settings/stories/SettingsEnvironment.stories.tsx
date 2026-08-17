import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import type { Meta, StoryObj } from '@storybook/react'
import { router } from 'kea-router'

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
    title: 'Scenes-App/Settings/Environment',
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
                '/api/billing/': { products: [] },
                '/api/projects/:id/integrations': { results: [] },
                '/api/projects/:id/core_memory': { results: [] },
                '/api/projects/:id/hog_functions': { results: [] },
                '/api/projects/:id/pipeline_destination_configs': { results: [] },
                '/api/organizations/:id/pipeline_destinations': { results: [] },
                '/api/environments/:id/batch_exports': { results: [] },
                '/api/environments/:id/default_evaluation_contexts/': {
                    default_evaluation_contexts: [],
                    available_contexts: [],
                    hidden_contexts: [],
                    enabled: false,
                },
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
    render: ({ sectionId }: StoryProps) => {
        // Navigate synchronously before <App /> mounts so it renders the settings scene directly,
        // never the project homepage. A useEffect push fires after the first paint, so the snapshot
        // can race and capture the homepage frame instead.
        router.actions.push(urls.settings(sectionId))

        return <App />
    },
}
export default meta

// -- Environment --
export const SettingsEnvironmentDetails: Story = { args: { sectionId: 'environment-details' } }

export const SettingsEnvironmentCustomization: Story = { args: { sectionId: 'environment-customization' } }

export const SettingsEnvironmentAutocapture: Story = { args: { sectionId: 'environment-autocapture' } }

export const SettingsEnvironmentHeatmaps: Story = { args: { sectionId: 'environment-heatmaps' } }

export const SettingsEnvironmentProductAnalytics: Story = { args: { sectionId: 'environment-product-analytics' } }

export const SettingsEnvironmentRevenueAnalytics: Story = { args: { sectionId: 'environment-revenue-analytics' } }

export const SettingsEnvironmentMarketingAnalytics: Story = {
    args: { sectionId: 'environment-marketing-analytics' },
    parameters: {
        featureFlags: [...STORYBOOK_FEATURE_FLAGS, 'advance-marketing-analytics-settings'],
    },
}

export const SettingsEnvironmentWebAnalytics: Story = { args: { sectionId: 'environment-web-analytics' } }

export const SettingsEnvironmentReplay: Story = { args: { sectionId: 'environment-replay' } }

export const SettingsEnvironmentSurveys: Story = { args: { sectionId: 'environment-surveys' } }

export const SettingsEnvironmentFeatureFlags: Story = { args: { sectionId: 'environment-feature-flags' } }

export const SettingsEnvironmentDataPipelines: Story = {
    args: { sectionId: 'environment-data-pipelines' },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:id/hog_functions': {
                    results: [
                        { id: '01930000-0000-4000-8000-000000000001', name: 'Webhook', type: 'destination' },
                        { id: '01930000-0000-4000-8000-000000000002', name: 'Drop bots', type: 'transformation' },
                    ],
                    next: null,
                },
                '/api/projects/:id/pipeline_notification_subscriptions/': [
                    {
                        user_id: 1,
                        uuid: '01930000-0000-4000-8000-000000000011',
                        first_name: 'Ada',
                        last_name: 'Kowalski',
                        email: 'ada@posthog.com',
                        organization_membership_level: 1,
                        editable: true,
                        pipeline_emails_enabled: true,
                        unsubscribed_pipeline_ids: ['hog_function:01930000-0000-4000-8000-000000000001'],
                    },
                    {
                        user_id: 2,
                        uuid: '01930000-0000-4000-8000-000000000012',
                        first_name: 'Bruno',
                        last_name: 'Sato',
                        email: 'bruno@posthog.com',
                        organization_membership_level: 8,
                        editable: true,
                        pipeline_emails_enabled: false,
                        unsubscribed_pipeline_ids: [],
                    },
                    {
                        user_id: 3,
                        uuid: '01930000-0000-4000-8000-000000000013',
                        first_name: 'Chidi',
                        last_name: 'Nwosu',
                        email: 'chidi@posthog.com',
                        organization_membership_level: 15,
                        editable: false,
                        pipeline_emails_enabled: true,
                        unsubscribed_pipeline_ids: [],
                    },
                ],
            },
        }),
    ],
}

export const SettingsEnvironmentErrorTracking: Story = { args: { sectionId: 'environment-error-tracking' } }

export const SettingsEnvironmentErrorTrackingConfiguration: Story = {
    args: { sectionId: 'environment-error-tracking-configuration' },
}

export const SettingsEnvironmentCSPReporting: Story = { args: { sectionId: 'environment-csp-reporting' } }

export const SettingsEnvironmentPrivacy: Story = { args: { sectionId: 'environment-privacy' } }

export const SettingsEnvironmentMax: Story = { args: { sectionId: 'environment-max' } }

export const SettingsEnvironmentIntegrations: Story = { args: { sectionId: 'environment-integrations' } }

export const SettingsEnvironmentAccessControl: Story = { args: { sectionId: 'environment-access-control' } }

export const SettingsEnvironmentDangerZone: Story = { args: { sectionId: 'environment-danger-zone' } }

import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

const TRACK_RULES_ENDPOINT = 'api/projects/:team_id/account_track_rules/'
const TRACK_RULE_RUNS_ENDPOINT = 'api/projects/:team_id/account_track_rules/runs/'
const CUSTOM_PROPERTY_DEFINITIONS_ENDPOINT = 'api/projects/:team_id/custom_property_definitions/'
const RELATIONSHIP_DEFINITIONS_ENDPOINT = 'api/projects/:team_id/account_relationship_definitions/'

const config = {
    schema_version: 1,
    version: 3,
    enabled: true,
    groups: [
        {
            conditions: [
                {
                    field: {
                        kind: 'custom_property',
                        definition_id: '01980d7c-0000-7000-8000-000000000001',
                    },
                    operator: 'gt',
                    values: [0],
                },
            ],
        },
        {
            conditions: [
                {
                    field: { kind: 'account_field', field: 'name' },
                    operator: 'icontains',
                    values: ['internal'],
                },
            ],
        },
    ],
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Customer Analytics/Track Rules',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        featureFlags: [
            FEATURE_FLAGS.CUSTOMER_ANALYTICS,
            FEATURE_FLAGS.CUSTOMER_ANALYTICS_CSP,
            FEATURE_FLAGS.CUSTOMER_ANALYTICS_TRACK_RULES,
        ],
        pageUrl: `${urls.customerAnalyticsConfiguration()}?tab=customer-analytics-track-rules`,
        testOptions: {
            waitForSelector: '[data-attr="account-track-rules"]',
        },
    },
    decorators: [
        mswDecorator({
            get: {
                [TRACK_RULES_ENDPOINT]: config,
                [TRACK_RULE_RUNS_ENDPOINT]: {
                    count: 1,
                    next: null,
                    previous: null,
                    results: [
                        {
                            id: '01980d7c-0000-7000-8000-000000000010',
                            config_version: 3,
                            trigger: 'manual',
                            status: 'completed',
                            eligible_active: 120,
                            skipped_churned: 12,
                            tracked: 95,
                            ignored: 25,
                            newly_ignored: 3,
                            restored: 2,
                            started_at: '2026-08-20T12:00:00Z',
                            finished_at: '2026-08-20T12:00:03Z',
                            error: null,
                            created_by: 1,
                            created_at: '2026-08-20T12:00:00Z',
                        },
                    ],
                },
                [CUSTOM_PROPERTY_DEFINITIONS_ENDPOINT]: {
                    count: 1,
                    next: null,
                    previous: null,
                    results: [
                        {
                            id: '01980d7c-0000-7000-8000-000000000001',
                            name: 'MRR',
                            description: 'Monthly recurring revenue',
                            display_type: 'currency',
                            is_canonical: false,
                            is_big_number: false,
                            options: null,
                        },
                    ],
                },
                [RELATIONSHIP_DEFINITIONS_ENDPOINT]: { count: 0, next: null, previous: null, results: [] },
            },
        }),
    ],
}

export default meta

type Story = StoryObj<{}>

export const Configured: Story = {
    render: () => <App />,
}

export const FeatureGateOff: Story = {
    render: () => <App />,
    parameters: {
        featureFlags: [FEATURE_FLAGS.CUSTOMER_ANALYTICS, FEATURE_FLAGS.CUSTOMER_ANALYTICS_CSP],
        testOptions: {
            waitForSelector: '[data-attr="settings-menu-item-customer-analytics-accounts"]',
        },
    },
}

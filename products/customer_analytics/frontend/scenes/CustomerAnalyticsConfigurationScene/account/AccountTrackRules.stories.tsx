import { Meta, StoryObj } from '@storybook/react'
import { within } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

const TRACK_RULES_ENDPOINT = 'api/projects/:team_id/account_track_rules/'
const TRACK_RULE_PREVIEW_ENDPOINT = 'api/projects/:team_id/account_track_rules/preview/'
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
            post: {
                [TRACK_RULE_PREVIEW_ENDPOINT]: {
                    config_version: 3,
                    eligible_active: 120,
                    skipped_churned: 12,
                    tracked: 95,
                    ignored: 25,
                    newly_ignored: 3,
                    restored: 2,
                    tracked_samples: [
                        { id: '01980d7c-0000-7000-8000-000000000101', name: 'Acme' },
                        { id: '01980d7c-0000-7000-8000-000000000102', name: 'Hooli' },
                        { id: '01980d7c-0000-7000-8000-000000000103', name: 'Initech' },
                        { id: '01980d7c-0000-7000-8000-000000000104', name: 'Pied Piper' },
                        { id: '01980d7c-0000-7000-8000-000000000105', name: 'Stark Industries' },
                    ],
                    ignored_samples: [
                        { id: '01980d7c-0000-7000-8000-000000000201', name: 'Massive Dynamic' },
                        { id: '01980d7c-0000-7000-8000-000000000202', name: 'Soylent Corp' },
                        { id: '01980d7c-0000-7000-8000-000000000203', name: 'Umbrella Corp' },
                        { id: '01980d7c-0000-7000-8000-000000000204', name: 'Wonka Industries' },
                        { id: '01980d7c-0000-7000-8000-000000000205', name: 'Cyberdyne Systems' },
                    ],
                    preview_token: 'signed-preview',
                    validation_errors: [],
                },
            },
        }),
    ],
}

export default meta

type Story = StoryObj<{}>

export const Configured: Story = {
    render: () => <App />,
}

export const Preview: Story = {
    render: () => <App />,
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        await userEvent.click(await canvas.findByRole('button', { name: 'Preview' }))
        await canvas.findByText('Preview results')
        await userEvent.click(await canvas.findByRole('button', { name: 'Excluded' }))
        await canvas.findByText('Massive Dynamic')
    },
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

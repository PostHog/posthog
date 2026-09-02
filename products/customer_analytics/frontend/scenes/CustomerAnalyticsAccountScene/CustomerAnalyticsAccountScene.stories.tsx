import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import { ACCOUNT_DETAIL_VIEWS_CONTEXT_KEY } from './accountDetailViews'

const ACCOUNT_ID = '0190da51-0b0e-7000-8000-000000000001'
const OWNER_DEFINITION_ID = '11111111-2222-3333-4444-555555555555'
const ARR_DEFINITION_ID = 'aaaaaaaa-0000-0000-0000-000000000001'
const RENEWAL_DEFINITION_ID = 'aaaaaaaa-0000-0000-0000-000000000002'
const SEATS_DEFINITION_ID = 'aaaaaaaa-0000-0000-0000-000000000003'

const account = {
    id: ACCOUNT_ID,
    name: 'Example Ltd',
    external_id: 'example-ltd',
    properties: { website_domain: 'example.com', slack_channel_id: null },
    tags: ['enterprise', 'renewal-risk'],
    notebooks: [],
    slack_summary_cadence: null,
    churned_at: null,
    ignored_at: null,
    created_at: '2025-11-04T10:00:00Z',
    created_by: null,
    updated_at: null,
}

const customPropertyDefinitions = {
    count: 3,
    results: [
        {
            id: ARR_DEFINITION_ID,
            name: 'Annual recurring revenue',
            display_type: 'currency',
            target_type: 'account',
            is_canonical: false,
            source: { id: 'src-1', definition: ARR_DEFINITION_ID, key_column: 'id', is_enabled: true },
            references: [],
        },
        {
            id: RENEWAL_DEFINITION_ID,
            name: 'Renews',
            display_type: 'date',
            target_type: 'account',
            is_canonical: false,
            source: { id: 'src-2', definition: RENEWAL_DEFINITION_ID, key_column: 'id', is_enabled: true },
            references: [],
        },
        {
            id: SEATS_DEFINITION_ID,
            name: 'Seat utilization',
            display_type: 'percent',
            target_type: 'account',
            is_canonical: false,
            source: null,
            references: [{ id: 'wf-1', name: 'Seat counter', status: 'active', type: 'workflow' }],
        },
    ],
}

const savedViews = {
    count: 2,
    results: [
        {
            id: 'view-overview',
            context_key: ACCOUNT_DETAIL_VIEWS_CONTEXT_KEY,
            name: 'Overview',
            columns: ['summary', 'usage', 'related_people', 'support_tickets'],
            visibility: 'shared',
            properties: {},
            created_by: 1,
            created_at: '2026-01-01T00:00:00Z',
            updated_at: '2026-01-01T00:00:00Z',
        },
        {
            id: 'view-support',
            context_key: ACCOUNT_DETAIL_VIEWS_CONTEXT_KEY,
            name: 'Support',
            columns: ['text', 'support_tickets'],
            visibility: 'private',
            properties: { text: 'Escalations go to the on-call engineer first.' },
            created_by: 1,
            created_at: '2026-01-01T00:00:00Z',
            updated_at: '2026-01-01T00:00:00Z',
        },
    ],
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Customer Analytics/Account detail',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-01-13',
        featureFlags: [
            FEATURE_FLAGS.CUSTOMER_ANALYTICS,
            FEATURE_FLAGS.CUSTOMER_ANALYTICS_CSP,
            FEATURE_FLAGS.CUSTOMER_ANALYTICS_ACCOUNT_SCENE,
        ],
        testOptions: {
            waitForSelector: '[data-attr="account-pinned-properties"]',
        },
    },
    decorators: [
        mswDecorator({
            get: {
                'api/projects/:team_id/accounts/:account_id/': account,
                'api/projects/:team_id/accounts/:account_id/custom_property_values/': [
                    { id: 'v1', account_id: ACCOUNT_ID, definition_id: ARR_DEFINITION_ID, value: 148000 },
                    { id: 'v2', account_id: ACCOUNT_ID, definition_id: RENEWAL_DEFINITION_ID, value: '2026-03-14' },
                    { id: 'v3', account_id: ACCOUNT_ID, definition_id: SEATS_DEFINITION_ID, value: 0.52 },
                ],
                'api/projects/:team_id/accounts/:account_id/relationships/': [
                    {
                        id: 'rel-row-1',
                        definition: { id: OWNER_DEFINITION_ID, name: 'Account owner', is_single_holder: true },
                        user: { id: 178, email: 'john.doe@example.com' },
                        started_at: '2025-12-01T00:00:00Z',
                        ended_at: null,
                    },
                ],
                'api/projects/:team_id/accounts/:account_id/summaries/': { count: 0, results: [] },
                'api/projects/:team_id/accounts/:account_id/support_tickets/': [],
                'api/projects/:team_id/accounts/:account_id/notebooks/': { count: 0, results: [] },
                'api/projects/:team_id/account_relationship_definitions/': {
                    count: 1,
                    results: [{ id: OWNER_DEFINITION_ID, name: 'Account owner', is_single_holder: true }],
                },
                'api/projects/:team_id/custom_property_definitions/': customPropertyDefinitions,
                'api/environments/:team_id/column_configurations/': savedViews,
                'api/projects/:team_id/organization_members/': { count: 0, results: [] },
                'api/environments/:team_id/customer_profile_configs/': { count: 0, results: [] },
                'api/environments/:team_id/warehouse_view_link/': { count: 0, results: [] },
                'api/projects/:team_id/accounts/': { count: 1, results: [account] },
                'api/projects/:team_id/feature_requests/': { count: 0, results: [] },
                'api/projects/:team_id/feature_request_product_areas/': { count: 0, results: [] },
            },
            post: {
                'api/environments/:team_id/query/': { results: [] },
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

export const Overview: Story = {
    parameters: {
        pageUrl: urls.customerAnalyticsAccount(ACCOUNT_ID),
    },
}

export const SupportView: Story = {
    parameters: {
        pageUrl: urls.customerAnalyticsAccount(ACCOUNT_ID, 'view-support'),
    },
}

import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

const ACCOUNT_ID = '11111111-2222-4333-8444-555555555555'
const ACCOUNT_RETRIEVE_ENDPOINT = 'api/projects/:team_id/accounts/:account_id/'
const ACCOUNT_NOTEBOOKS_ENDPOINT = 'api/projects/:team_id/accounts/:account_id/notebooks/'
const ACCOUNT_ICON_ENDPOINT = 'api/projects/:team_id/accounts/icon/'

const account = {
    id: ACCOUNT_ID,
    name: 'Example Labs',
    external_id: 'example_labs_42',
    properties: {
        website_domain: 'example.com',
        email_domains: ['example.com'],
        known_emails: [],
    },
    tags: ['enterprise', 'onboarding'],
    notebooks: ['note1234'],
    slack_summary_cadence: null,
    churned_at: null,
    ignored_at: null,
    created_at: '2026-05-10T10:00:00Z',
    created_by: null,
    updated_at: '2026-05-20T14:30:00Z',
}

const notebooks = {
    count: 1,
    next: null,
    previous: null,
    results: [
        {
            id: 'aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee',
            short_id: 'note1234',
            title: 'Implementation planning',
            content: null,
            text_content: 'The team plans to finish its data import and review the first dashboard next week.',
            created_at: '2026-05-18T09:15:00Z',
            created_by: {
                id: 7,
                uuid: '99999999-8888-4777-8666-555555555555',
                email: 'alex@example.com',
                first_name: 'Alex',
                last_name: 'River',
                is_email_verified: true,
            },
            last_modified_at: '2026-05-18T09:15:00Z',
            last_modified_by: null,
        },
    ],
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Customer Analytics/Account detail',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-05-21',
        featureFlags: [
            FEATURE_FLAGS.CUSTOMER_ANALYTICS,
            FEATURE_FLAGS.CUSTOMER_ANALYTICS_CSP,
            FEATURE_FLAGS.CUSTOMER_ANALYTICS_ACCOUNT_SCENE,
        ],
        pageUrl: urls.customerAnalyticsAccount(ACCOUNT_ID),
        testOptions: {
            waitForSelector: ['[data-attr="customer-analytics-account-scene"]', '[data-attr="account-notes"]'],
            viewport: { width: 1280, height: 900 },
        },
    },
    decorators: [
        mswDecorator({
            get: {
                [ACCOUNT_RETRIEVE_ENDPOINT]: account,
                [ACCOUNT_NOTEBOOKS_ENDPOINT]: notebooks,
                [ACCOUNT_ICON_ENDPOINT]: () =>
                    new Response(
                        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><rect width="24" height="24" rx="4" fill="#8f68d4"/></svg>',
                        { headers: { 'Content-Type': 'image/svg+xml' } }
                    ),
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

export const Default: Story = {
    render: () => <App />,
}

export const Narrow: Story = {
    render: () => <App />,
    parameters: {
        testOptions: {
            waitForSelector: '[data-attr="customer-analytics-account-scene"]',
            viewport: { width: 800, height: 900 },
        },
    },
}

import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

const ACCOUNTS_ENDPOINT = 'api/environments/:team_id/accounts/'

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Customer Analytics/Accounts',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-05-21',
        featureFlags: [FEATURE_FLAGS.CUSTOMER_ANALYTICS, FEATURE_FLAGS.CUSTOMER_ANALYTICS_CSP],
        pageUrl: urls.customerAnalyticsAccounts(),
        testOptions: {
            waitForSelector: '[data-attr="accounts-refresh"]',
        },
    },
    decorators: [
        mswDecorator({
            get: {
                [ACCOUNTS_ENDPOINT]: {
                    count: 3,
                    next: null,
                    previous: null,
                    results: [
                        {
                            id: 'acc-1',
                            name: 'Acme Inc',
                            external_id: 'cust_acme_001',
                            properties: {
                                csm: { id: 1, email: 'alice@posthog.com' },
                                account_executive: { id: 2, email: 'bob@posthog.com' },
                                account_owner: null,
                            },
                            tags: ['enterprise', 'priority'],
                            created_at: '2026-05-01T00:00:00Z',
                            created_by: 1,
                            updated_at: '2026-05-20T00:00:00Z',
                        },
                        {
                            id: 'acc-2',
                            name: 'Globex',
                            external_id: 'cust_globex_002',
                            properties: {},
                            tags: [],
                            created_at: '2026-05-02T00:00:00Z',
                            created_by: 1,
                            updated_at: '2026-05-19T00:00:00Z',
                        },
                        {
                            id: 'acc-3',
                            name: 'Hooli',
                            external_id: null,
                            properties: {
                                csm: { id: 1, email: 'alice@posthog.com' },
                                account_executive: null,
                                account_owner: { id: 3, email: 'carol@posthog.com' },
                            },
                            tags: ['scaleup'],
                            created_at: '2026-05-03T00:00:00Z',
                            created_by: 1,
                            updated_at: '2026-05-18T00:00:00Z',
                        },
                    ],
                },
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

export const Default: Story = {
    render: () => <App />,
}

export const Empty: Story = {
    render: () => <App />,
    decorators: [
        mswDecorator({
            get: {
                [ACCOUNTS_ENDPOINT]: { count: 0, next: null, previous: null, results: [] },
            },
        }),
    ],
}

// CUSTOMER_ANALYTICS must stay enabled (the outer scene gate) so we get past it;
// without CUSTOMER_ANALYTICS_CSP the accounts URL is treated as a 404.
export const FeatureGateOff: Story = {
    render: () => <App />,
    parameters: {
        featureFlags: [FEATURE_FLAGS.CUSTOMER_ANALYTICS],
        testOptions: {
            waitForSelector: '[data-attr="not-found-page"]',
        },
    },
}

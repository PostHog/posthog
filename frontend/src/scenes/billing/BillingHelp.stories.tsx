import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator, useStorybookMocks } from '~/mocks/browser'
import { billingJson } from '~/mocks/fixtures/_billing'
import preflightJson from '~/mocks/fixtures/_preflight.json'

import { BillingHelp } from './BillingHelp'

const meta: Meta = {
    title: 'Scenes-Other/Billing/Help',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2024-03-10',
        featureFlags: [FEATURE_FLAGS.BILLING_OPTIMIZE_SPEND],
        testOptions: { snapshotBrowsers: [], viewport: { width: 1300, height: 900 } },
    },
    decorators: [
        mswDecorator({
            get: {
                '/_preflight': { ...preflightJson, cloud: true, realm: 'cloud', wizard_cloud_run_available: true },
                '/api/environments/:team_id/integrations/': { results: [], next: null },
                '/api/projects/:team_id/wizard/registry/': { count: 0, results: [], next: null, previous: null },
                '/api/projects/:team_id/wizard/runs/': { count: 0, results: [], next: null, previous: null },
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

export const WithAccountContact: Story = {
    render: () => {
        useStorybookMocks({
            get: {
                '/api/billing/': { ...billingJson, account_owner: { name: 'Alex Example', email: 'alex@example.com' } },
            },
        })
        return <BillingHelp />
    },
}

export const WithoutAccountContact: Story = {
    render: () => {
        useStorybookMocks({
            get: {
                '/api/billing/': { ...billingJson, account_owner: null },
            },
        })
        return <BillingHelp />
    },
}

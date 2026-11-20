import type { Meta, StoryObj } from '@storybook/react'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'

import { accountContextResponse } from '../../__mocks__/accountContextResponse'
import { AccountContextPane } from './AccountContextPane'

const RUN_ENDPOINT = '/api/projects/:project_id/endpoints/:name/run/'

const SOURCE = { project_id: 1, endpoint: 'account-context', account_variable: 'account_key' }

const RESPONSE = accountContextResponse([
    { section: 'meta', id: 'contract', expired_facts: 1 },
    {
        section: 'fact',
        id: 'fact-renewal',
        author: 'alex@example.com',
        fact_text: 'The renewal closed in July with a prepaid credit purchase.',
        confidence: 'confirmed',
        review_due: 0,
        fact_source: 'session',
        valid_from: '2026-07-08',
    },
    {
        section: 'fact',
        id: 'fact-dashboards',
        author: 'morgan@example.com',
        fact_text: 'The team wants one dashboard for every major feature by the end of the quarter.',
        confidence: 'confirmed',
        review_due: 1,
        fact_source: 'gong',
        valid_from: '2026-10-02',
    },
    {
        section: 'fact',
        id: 'fact-polling',
        author: 'alex@example.com',
        fact_text: 'One backend service probably polls flags in a loop.',
        confidence: 'inferred',
        review_due: 0,
        fact_source: 'session',
        valid_from: '2026-10-14',
    },
    {
        section: 'signal',
        id: 'signal-flags',
        signal_type: 'usage_spike',
        direction: 'up',
        signal_state: 'open',
        onset: '2026-10-05',
        change: 8,
        arr_at_stake: 48000,
    },
    {
        section: 'signal',
        id: 'signal-cap',
        signal_type: 'cap_hit',
        direction: 'down',
        signal_state: 'open',
        onset: '2026-11-10',
    },
    {
        section: 'slack',
        id: 'https://example.slack.com/archives/C000/p1',
        summary: 'The customer asked how to raise the flag request limit.',
        observed_on: '2026-11-04',
    },
    { section: 'node', id: 'product:feature_flags', node_kind: 'product', node_name: 'Feature flags' },
    { section: 'node', id: 'subject:contract', node_kind: 'subject', node_name: 'Contract and renewal' },
    { section: 'node', id: 'feature:dashboards', node_kind: 'feature', node_name: 'Dashboards' },
    { section: 'link', id: 'fact-renewal', to_id: 'subject:contract', relation: 'about' },
    { section: 'link', id: 'fact-dashboards', to_id: 'feature:dashboards', relation: 'about' },
    { section: 'link', id: 'fact-polling', to_id: 'product:feature_flags', relation: 'about' },
    { section: 'link', id: 'signal-flags', to_id: 'product:feature_flags', relation: 'on' },
    {
        section: 'link',
        id: 'signal-flags',
        to_id: 'fact-polling',
        relation: 'explains',
        link_source: 'explain',
    },
])

const meta: Meta<typeof AccountContextPane> = {
    title: 'Customer Analytics/Account views/Context',
    component: AccountContextPane,
    args: { accountId: 'example-account', externalId: 'example-account-key', instanceId: 'example-context-tile' },
    parameters: {
        mockDate: '2026-11-19T12:00:00Z',
        featureFlags: [FEATURE_FLAGS.CUSTOMER_ANALYTICS_CONTEXT_PANE],
        testOptions: { snapshotBrowsers: [] },
    },
    beforeEach: ({ parameters }) => {
        const original = posthog.getFeatureFlagResult
        posthog.getFeatureFlagResult = ((key, options) =>
            key === FEATURE_FLAGS.CUSTOMER_ANALYTICS_CONTEXT_PANE
                ? { key, enabled: true, variant: undefined, payload: parameters.contextSource ?? SOURCE }
                : original.call(posthog, key, options)) as typeof posthog.getFeatureFlagResult
        return () => {
            posthog.getFeatureFlagResult = original
        }
    },
    decorators: [
        (Story, { parameters }) => (
            <div className={parameters.narrow ? 'w-128 p-2' : 'w-192 p-2'}>
                <Story />
            </div>
        ),
    ],
}
export default meta

type Story = StoryObj<typeof AccountContextPane>

export const Loaded: Story = {
    decorators: [mswDecorator({ post: { [RUN_ENDPOINT]: RESPONSE } })],
    parameters: { testOptions: { snapshotBrowsers: [], waitForSelector: '[data-attr="account-context-summary"]' } },
}

export const NotSetUp: Story = {
    parameters: {
        contextSource: { project_id: 1 },
        testOptions: { snapshotBrowsers: [], waitForSelector: '[data-attr="account-context-not-set-up"]' },
    },
}

export const LoadFailed: Story = {
    decorators: [mswDecorator({ post: { [RUN_ENDPOINT]: () => [500, { detail: 'Unavailable' }] } })],
    parameters: { testOptions: { snapshotBrowsers: [], waitForSelector: '[data-attr="account-context-retry"]' } },
}

export const Narrow: Story = {
    decorators: [mswDecorator({ post: { [RUN_ENDPOINT]: RESPONSE } })],
    parameters: {
        narrow: true,
        testOptions: { snapshotBrowsers: [], waitForSelector: '[data-attr="account-context-summary"]' },
    },
}

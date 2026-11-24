import type { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import { METRICS, RANGE_TOO_LONG_DETAIL } from './homeFixtures'
import { HomeHost } from './HomeHost'

const METRICS_URL = '/api/projects/:team_id/ai_observability/traces/metrics/'
const DASHBOARDS_URL = '/api/projects/:team_id/dashboards/'
const DASHBOARDS = { count: 1, results: [{ id: 42, name: 'LLM analytics' }] }

const meta: Meta<typeof HomeHost> = {
    title: 'Scenes-App/AI observability/Home/Home host',
    component: HomeHost,
    decorators: [mswDecorator({})],
    parameters: {
        msw: { mocks: { get: { [METRICS_URL]: METRICS, [DASHBOARDS_URL]: DASHBOARDS } } },
        mockDate: '2026-11-19',
        pageUrl: urls.aiObservabilityDashboard(),
        featureFlags: [FEATURE_FLAGS.AI_OBSERVABILITY_NAV_REDESIGN],
        testOptions: { snapshotBrowsers: [], waitForSelector: '[data-attr="home-tile-traces"]' },
    },
}
export default meta

type Story = StoryObj<typeof HomeHost>

export const Loaded: Story = {}

export const RangeTooLong: Story = {
    parameters: {
        msw: {
            mocks: {
                get: {
                    [METRICS_URL]: () => [422, { detail: RANGE_TOO_LONG_DETAIL, code: 'range_too_long' }],
                    [DASHBOARDS_URL]: DASHBOARDS,
                },
            },
        },
        testOptions: { snapshotBrowsers: [], waitForSelector: 'text=too long to compute' },
    },
}

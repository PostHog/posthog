import type { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'
import { NodeKind } from '~/queries/schema/schema-general'

import { MetricsPanelEditor } from './MetricsPanelEditor'

const meta: Meta<typeof MetricsPanelEditor> = {
    title: 'Products/Dashboards/Metrics panel editor',
    component: MetricsPanelEditor,
    parameters: {
        layout: 'fullscreen',
        mockDate: '2026-01-15',
        featureFlags: [
            FEATURE_FLAGS.METRICS,
            FEATURE_FLAGS.METRICS_INSIGHT_BUILDER,
            FEATURE_FLAGS.METRICS_QUERY_LANGUAGES,
        ],
        testOptions: { waitForSelector: '[data-attr="metrics-query-editor"]' },
    },
    args: { projectId: 2, insightId: 101, filtersOverride: { date_from: '-1h' }, onClose: () => {}, onSaved: () => {} },
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/insights/101/': {
                    id: 101,
                    short_id: 'requests1',
                    name: 'Request volume',
                    user_access_level: 'editor',
                    query: {
                        kind: NodeKind.MetricsQuery,
                        language: 'promql',
                        promql: 'sum(rate(http_requests_total[5m]))',
                        clauses: [],
                        dateRange: { date_from: '-24h' },
                    },
                    dashboard_tiles: [
                        { id: 1, dashboard_id: 5 },
                        { id: 2, dashboard_id: 6 },
                    ],
                },
            },
            post: {
                '/api/environments/:team_id/query/:kind': {
                    results: [
                        {
                            labels: {},
                            points: [
                                { time: '2026-01-14T23:00:00Z', value: 120 },
                                { time: '2026-01-14T23:30:00Z', value: 135 },
                                { time: '2026-01-15T00:00:00Z', value: 128 },
                            ],
                        },
                    ],
                },
            },
        }),
    ],
}
export default meta
type Story = StoryObj<typeof MetricsPanelEditor>
export const SharedMetricsInsight: Story = {}

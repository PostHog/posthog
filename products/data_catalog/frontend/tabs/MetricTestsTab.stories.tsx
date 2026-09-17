import type { Meta, StoryObj } from '@storybook/react'
import { BindLogic } from 'kea'

import { useStorybookMocks } from '~/mocks/browser'

import { dataCatalogMetricSceneLogic } from '../dataCatalogMetricSceneLogic'
import { MetricTestsTab } from './MetricTestsTab'

interface StoryProps {
    definitionKind: string | null
    hasCheck: boolean
}

const meta: Meta<StoryProps> = {
    title: 'Data catalog/Metric tests',
    args: { definitionKind: 'HogQLQuery', hasCheck: false },
    parameters: { mockDate: '2026-09-04', viewMode: 'story' },
    render: ({ definitionKind, hasCheck }) => {
        useStorybookMocks({
            get: {
                '/api/projects/:team_id/data_catalog/metrics/signups/': {
                    id: 'metric-1',
                    name: 'signups',
                    definition_kind: definitionKind,
                },
                '/api/projects/:team_id/data_catalog/metrics/metric-1/checks/': {
                    results: hasCheck
                        ? [
                              {
                                  id: 'check-1',
                                  name: 'daily_signups',
                                  check_type: 'custom_sql',
                                  column_name: '',
                                  enabled: true,
                                  severity: 'error',
                                  last_status: 'failed',
                                  config: { query: 'SELECT * FROM {metric} WHERE signups < 100' },
                                  tags: [],
                              },
                          ]
                        : [],
                },
                '/api/projects/:team_id/data_catalog/metrics/metric-1/checks/health/': {
                    health: hasCheck ? 'failing' : 'unknown',
                    checks_total: hasCheck ? 1 : 0,
                    checks_failing: hasCheck ? 1 : 0,
                },
                '/api/projects/:team_id/data_catalog/metrics/metric-1/checks/check_types/': [
                    {
                        check_type: 'custom_sql',
                        description: 'Return one row per failure.',
                        requires_column: false,
                        config_schema: {},
                    },
                ],
                '/api/projects/:team_id/data_catalog/metrics/metric-1/check_suite_runs/': { results: [] },
                '/api/projects/:team_id/data_catalog/metrics/metric-1/checks/schedule/': {
                    id: 'schedule-1',
                    enabled: true,
                    interval: '24hour',
                    next_run_at: '2026-09-05T00:00:00Z',
                    last_run_at: null,
                    last_suite_run: null,
                },
            },
        })
        return (
            <BindLogic logic={dataCatalogMetricSceneLogic} props={{ name: 'signups' }}>
                <div className="max-w-2xl">
                    <MetricTestsTab />
                </div>
            </BindLogic>
        )
    },
}

export default meta
type Story = StoryObj<StoryProps>
export const Empty: Story = {}
export const Scheduled: Story = { args: { hasCheck: true } }
export const Unsupported: Story = { args: { definitionKind: 'MarkdownDefinition' } }
export const UnsupportedWithChecks: Story = { args: { definitionKind: 'MarkdownDefinition', hasCheck: true } }
export const Narrow: Story = {
    args: { hasCheck: true },
    decorators: [
        (Story) => (
            <div className="w-128">
                <Story />
            </div>
        ),
    ],
}

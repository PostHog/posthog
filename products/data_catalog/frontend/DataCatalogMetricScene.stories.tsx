import type { Meta, StoryObj } from '@storybook/react'
import { BindLogic } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'

import { useStorybookMocks } from '~/mocks/browser'

import { DataCatalogMetricScene } from './DataCatalogMetricScene'
import { dataCatalogMetricSceneLogic } from './dataCatalogMetricSceneLogic'
import type { DataCatalogMetricApi } from './generated/api.schemas'

const METRIC_NAME = 'weekly_active_accounts'

function metric(overrides: Partial<DataCatalogMetricApi> = {}): DataCatalogMetricApi {
    return {
        id: 'metric-1',
        name: METRIC_NAME,
        display_name: 'Weekly active accounts',
        description: 'Accounts with at least one event in the last 7 days.',
        definition: {
            kind: 'HogQLQuery',
            query: 'SELECT count(DISTINCT properties.$group_0) AS value\nFROM events\nWHERE timestamp > now() - INTERVAL 7 DAY',
        },
        definition_kind: 'HogQLQuery',
        status: 'proposed',
        is_drifted: false,
        owner: 'alex@example.com',
        unit: 'accounts',
        approved_by: null,
        approved_at: null,
        last_run_at: '2026-09-03T10:00:00Z',
        created_source: 'ai_generated',
        ai_model: 'example-model',
        confidence: 0.82,
        reasoning: 'Counts distinct accounts that sent any event in the last week.',
        created_at: '2026-09-01T00:00:00Z',
        updated_at: '2026-09-01T00:00:00Z',
        ...overrides,
    } as DataCatalogMetricApi
}

const DRIFTED_MARKDOWN_METRIC = metric({
    definition_kind: 'MarkdownDefinition',
    definition: {
        kind: 'MarkdownDefinition',
        markdown: '1. Count accounts with a paid plan\n2. Exclude internal test accounts',
    },
    status: 'approved',
    is_drifted: true,
    source_insight_short_id: 'abc123',
    approved_by: { id: 2, uuid: 'user-2', email: 'sam@example.com', hedgehog_config: null },
    approved_at: '2026-09-02T09:00:00Z',
    created_source: 'user',
})

interface StoryProps {
    metric: DataCatalogMetricApi
    className: string
}

const meta: Meta<StoryProps> = {
    title: 'Products/Data catalog/Metric',
    args: { metric: metric(), className: 'w-[960px] @container/main-content' },
    parameters: {
        layout: 'padded',
        viewMode: 'story',
        mockDate: '2026-09-04',
        featureFlags: [FEATURE_FLAGS.TODAY_RAIL_NAV, FEATURE_FLAGS.DATA_CATALOG_RESTRUCTURE],
        testOptions: { snapshotBrowsers: [] },
    },
    render: ({ metric: storyMetric, className }) => {
        useStorybookMocks({
            get: {
                [`/api/projects/:team_id/data_catalog/metrics/${METRIC_NAME}/`]: storyMetric,
                '/api/projects/:team_id/data_quality_checks/': { results: [] },
                '/api/projects/:team_id/data_quality_checks/health/': [],
                '/api/projects/:team_id/data_quality_runs/': { results: [] },
                '/api/organizations/:organization_id/members/': {
                    results: [
                        {
                            id: 'member-1',
                            level: 8,
                            user: {
                                id: 1,
                                uuid: 'user-1',
                                email: 'alex@example.com',
                                first_name: 'Alex',
                                last_name: 'Rivera',
                            },
                        },
                    ],
                },
            },
        })
        return (
            <BindLogic logic={dataCatalogMetricSceneLogic} props={{ name: METRIC_NAME }}>
                <div className={className}>
                    <DataCatalogMetricScene name={METRIC_NAME} />
                </div>
            </BindLogic>
        )
    },
}
export default meta

type Story = StoryObj<StoryProps>

export const QuillProposedSqlMetric: Story = {}

export const QuillProposedSqlMetricNarrow: Story = { args: { className: 'w-130 @container/main-content' } }

export const QuillWithSceneMenuBar: Story = {
    parameters: {
        featureFlags: [
            FEATURE_FLAGS.TODAY_RAIL_NAV,
            FEATURE_FLAGS.DATA_CATALOG_RESTRUCTURE,
            FEATURE_FLAGS.SCENE_MENU_BAR,
        ],
    },
}

export const QuillDriftedMarkdownMetric: Story = { args: { metric: DRIFTED_MARKDOWN_METRIC } }

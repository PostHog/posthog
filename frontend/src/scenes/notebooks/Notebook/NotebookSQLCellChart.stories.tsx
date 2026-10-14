import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import { notebookTestTemplate } from './__mocks__/notebook-template-for-snapshot'
import { buildMarkdownNotebookContent } from './markdownNotebookV2'

const RESULT = {
    columns: ['month', 'orgs'],
    types: [
        ['month', 'Date'],
        ['orgs', 'UInt64'],
    ],
    row_count: 6,
    first_page: [
        ['2023-01-01', 120],
        ['2023-02-01', 180],
        ['2023-03-01', 150],
        ['2023-04-01', 240],
        ['2023-05-01', 310],
        ['2023-06-01', 290],
    ],
    has_more: false,
}

// The tag exactly as the MCP notebooks-add-cell tool writes it for a cell with a visualization.
const sqlCellTag = (display: string): string =>
    `<SQLV2 nodeId="0d3f7a52-9c1e-4d7b-a8f0-5b2c6e1d9a44" title="Orgs by month" code="select month, orgs from monthly_orgs" returnVariable="sql_df" outputTab="visualization" vizQuery={${JSON.stringify(
        {
            kind: 'DataVisualizationNode',
            display,
            chartSettings: { xAxis: { column: 'month' }, yAxis: [{ column: 'orgs' }] },
        }
    )}} runId="run-1" result={${JSON.stringify(RESULT)}} />`

const notebooks = {
    'sql-cell-bar-chart': {
        ...notebookTestTemplate('SQL cell bar chart', []),
        content: buildMarkdownNotebookContent(`# SQL cell bar chart\n\n${sqlCellTag('ActionsBar')}`),
    },
    'sql-cell-line-chart': {
        ...notebookTestTemplate('SQL cell line chart', []),
        content: buildMarkdownNotebookContent(`# SQL cell line chart\n\n${sqlCellTag('ActionsLineGraph')}`),
    },
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Notebooks/SQL cell chart',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-07-04',
        featureFlags: [FEATURE_FLAGS.REVAMPED_PY_NOTEBOOKS],
        testOptions: {
            waitForSelector: '[data-attr="notebook-node-sql-v2"] canvas',
        },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/notebooks/:short_id/sql_v2/runs/:run_id': {
                    status: 'done',
                    result: RESULT,
                    error: null,
                },
                '/api/projects/:team_id/notebooks/kernel/compute_options': {
                    currency: 'USD',
                    cpu_rate_per_core_hour: 0.2,
                    memory_rate_per_gb_hour: 0.025,
                    default_preset_key: 'small',
                    presets: [
                        {
                            key: 'small',
                            name: 'Small',
                            description: 'Exploring data and working with small dataframes.',
                            cpu_cores: 1,
                            memory_gb: 2,
                            hourly_price: 0.25,
                        },
                    ],
                    allowed_cpu_cores: [1],
                    allowed_memory_gb: [2],
                    allowed_idle_timeout_seconds: [3600],
                },
                '/api/projects/:team_id/notebooks/:short_id': ({ params }) => [
                    200,
                    { ...notebooks[params.short_id as keyof typeof notebooks], short_id: params.short_id },
                ],
            },
            post: {
                '/api/projects/:team_id/notebooks/:short_id/collab/markdown_save': async ({ params, request }) => {
                    const body = (await request.json()) as Record<string, unknown> & { version: number }
                    return {
                        ...notebooks[params.short_id as keyof typeof notebooks],
                        short_id: params.short_id,
                        ...body,
                        version: body.version + 1,
                    }
                },
            },
        }),
    ],
}

export default meta

type Story = StoryObj<{}>

export const BarChart: Story = { parameters: { pageUrl: urls.notebook('sql-cell-bar-chart') } }
export const LineChart: Story = { parameters: { pageUrl: urls.notebook('sql-cell-line-chart') } }

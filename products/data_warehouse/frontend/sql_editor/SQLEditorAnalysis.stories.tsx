import { Meta } from '@storybook/react'
import { waitFor, within } from '@testing-library/dom'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import type { MockResolverInfo, Mocks } from '~/mocks/utils'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { BIConfig, BIField } from '~/queries/schema/schema-business-intelligence'
import { NodeKind } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import {
    buildBIQuery,
    getBIResultDimensions,
    getBIResultMeasureColumns,
} from 'products/business_intelligence/frontend/biEditorTypes'
import { biSceneLogic } from 'products/business_intelligence/frontend/biSceneLogic'

import { expect, userEvent } from 'storybook/test'

import {
    biEventsField,
    BI_WORKSHEET_CONFIG,
    BI_EVENTS_FIELDS,
    Story,
    BI_MODE_WORKSHEET_MOCKS,
    biWorksheetStory,
    sqlEditorStoryMeta,
} from './__mocks__/SQLEditorStoryFixtures'

const meta: Meta = { ...sqlEditorStoryMeta, component: App, title: 'Scenes-App/Data Warehouse/SQL Editor' }
export default meta

const BI_ANALYSIS_CONFIG: BIConfig = {
    ...BI_WORKSHEET_CONFIG,
    chartType: ChartDisplayType.ActionsTable,
    values: [
        { field: biEventsField('revenue', 'float'), aggregation: 'sum', tableCalculation: { type: 'running_total' } },
        { field: biEventsField('revenue', 'float'), aggregation: 'average' },
    ],
    topN: { fieldId: biEventsField('event', 'string').id, count: 5, measureIndex: 0, includeOther: true },
    totals: { rows: true, subtotals: true },
}

async function stabilizeQueryElapsedTime(): Promise<void> {
    const { dataNodeKey } = biSceneLogic({ tabId: 'bi-default' }).values
    const logic = dataNodeLogic.findMounted({ key: dataNodeKey })
    await waitFor(() => {
        expect(logic).toBeDefined()
        expect(logic?.values.responseLoading).toBe(false)
        expect(logic?.values.response).toBeTruthy()
    })
    // MSW fixes the response, but the query timer still measures real browser time.
    logic!.actions.setElapsedTime(180)
}

const BI_TABLE_ANALYSIS_MOCKS = {
    ...BI_MODE_WORKSHEET_MOCKS,
    post: {
        ...BI_MODE_WORKSHEET_MOCKS.post,
        '/api/environments/:team_id/query/HogQLQuery/': {
            columns: ['bi_row_timestamp', 'bi_column_event', 'sum_revenue', 'average_revenue_2'],
            types: [
                ['bi_row_timestamp', 'String'],
                ['bi_column_event', 'String'],
                ['sum_revenue', 'Nullable(Float64)'],
                ['average_revenue_2', 'Float64'],
            ],
            results: [
                ['Total', 'Total', null, 14.2],
                ['2026-06-01', 'purchase', 120, 12],
                ['2026-06-02', 'purchase', 300, 15],
                ['2026-06-01', 'Other', 40, 10],
            ],
            hasMore: false,
        },
    },
} satisfies Mocks

export const BITableAnalysis: Story = {
    ...biWorksheetStory,
    parameters: {
        ...biWorksheetStory.parameters,
        pageUrl: `${urls.businessIntelligence()}#${new URLSearchParams({
            q: buildBIQuery(BI_ANALYSIS_CONFIG)!.query,
            mode: 'bi',
            bi: JSON.stringify(BI_ANALYSIS_CONFIG),
        })}`,
        msw: {
            mocks: BI_TABLE_ANALYSIS_MOCKS,
        },
    },
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        await waitFor(() => expect(canvasElement.querySelector('[data-attr="bi-editor-data-source"]')).toBeVisible())
        await userEvent.click(await canvas.findByRole('button', { name: /^Run$/ }))
        await waitFor(() => expect(canvas.getAllByText('Total').length).toBeGreaterThan(0))
        await stabilizeQueryElapsedTime()
    },
}

const BI_COMBO_CONFIG: BIConfig = {
    ...BI_WORKSHEET_CONFIG,
    chartType: ChartDisplayType.ActionsBar,
    columns: [],
    values: [
        {
            field: biEventsField('revenue', 'float'),
            aggregation: 'sum',
            formatting: { style: 'number', prefix: '$', decimalPlaces: 2 },
            display: { label: 'Revenue', displayType: 'bar', yAxisPosition: 'left' },
        },
        {
            field: biEventsField('revenue', 'float'),
            aggregation: 'average',
            formatting: { style: 'number', prefix: '$', decimalPlaces: 2 },
            display: { label: 'Average order', displayType: 'line', yAxisPosition: 'right' },
        },
    ],
}

const BI_COMBINED_MEASURES_MOCKS = {
    ...BI_MODE_WORKSHEET_MOCKS,
    post: {
        ...BI_MODE_WORKSHEET_MOCKS.post,
        '/api/environments/:team_id/query/HogQLQuery/': {
            columns: ['toStartOfDay(timestamp)', 'sum_revenue', 'average_revenue_2'],
            types: [
                ['toStartOfDay(timestamp)', 'DateTime'],
                ['sum_revenue', 'Float64'],
                ['average_revenue_2', 'Float64'],
            ],
            results: [
                ['2026-06-01', 1200, 12.5],
                ['2026-06-02', 2100, 15.2],
                ['2026-06-03', 1800, 13.4],
                ['2026-06-04', 2450, 16.8],
            ],
            hasMore: false,
        },
    },
} satisfies Mocks

export const BICombinedMeasures: Story = {
    ...biWorksheetStory,
    parameters: {
        ...biWorksheetStory.parameters,
        pageUrl: `${urls.businessIntelligence()}#${new URLSearchParams({ q: buildBIQuery(BI_COMBO_CONFIG)!.query, mode: 'bi', bi: JSON.stringify(BI_COMBO_CONFIG) })}`,
        msw: {
            mocks: BI_COMBINED_MEASURES_MOCKS,
        },
    },
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        await waitFor(() => expect(canvasElement.querySelector('[data-attr="bi-editor-data-source"]')).toBeVisible())
        await userEvent.click(await canvas.findByRole('button', { name: /^Run$/ }))
        await waitFor(() => expect(canvasElement.querySelector('canvas')).not.toBeNull())
        await stabilizeQueryElapsedTime()
    },
}

export const BIMeasureDisplay: Story = {
    ...BICombinedMeasures,
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        await userEvent.click(await canvas.findByRole('button', { name: /^Charts$/ }))
        await userEvent.click((await canvas.findAllByRole('button', { name: 'Format and display' }))[0])
    },
}

export const BIDrilldown: Story = {
    ...BITableAnalysis,
    parameters: {
        ...BITableAnalysis.parameters,
        // The dialog is portaled outside main, so a scene-only capture clips it.
        testOptions: { ...BITableAnalysis.parameters?.testOptions, includeNavigationInSnapshot: true },
        msw: {
            mocks: {
                ...BI_TABLE_ANALYSIS_MOCKS,
                post: {
                    ...BI_TABLE_ANALYSIS_MOCKS.post,
                    '/api/environments/:team_id/query/HogQLQuery/': async ({ request }: MockResolverInfo) => {
                        const { query } = (await request.json()) as { query: { query: string } }
                        return query.query.startsWith('SELECT *')
                            ? {
                                  columns: ['event', 'timestamp', 'revenue'],
                                  types: [
                                      ['event', 'String'],
                                      ['timestamp', 'DateTime'],
                                      ['revenue', 'Float64'],
                                  ],
                                  results: [
                                      ['purchase', '2026-06-01 12:00:00', 20],
                                      ['purchase', '2026-06-01 15:00:00', 100],
                                  ],
                                  hasMore: false,
                              }
                            : BI_TABLE_ANALYSIS_MOCKS.post['/api/environments/:team_id/query/HogQLQuery/']
                    },
                },
            },
        },
    },
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        await userEvent.click(await canvas.findByRole('button', { name: /^Run$/ }))
        await userEvent.click(await canvas.findByText('120', { exact: true }))
        await userEvent.click(await within(document.body).findByRole('button', { name: 'View underlying rows' }))
        await waitFor(() => expect(within(document.body).getByText('2026-06-01 12:00:00')).toBeVisible())
        await stabilizeQueryElapsedTime()
    },
}

const BI_COMPARISON_CONFIG: BIConfig = {
    ...BI_COMBO_CONFIG,
    dateRange: { date_from: '-7d' },
    compareFilter: { compare: true },
    values: [BI_COMBO_CONFIG.values[0]],
}

export const BIOneClickComparison: Story = {
    ...BICombinedMeasures,
    parameters: {
        ...BICombinedMeasures.parameters,
        pageUrl: `${urls.businessIntelligence()}#${new URLSearchParams({ q: buildBIQuery(BI_COMPARISON_CONFIG)!.query, mode: 'bi', bi: JSON.stringify(BI_COMPARISON_CONFIG) })}`,
        msw: {
            mocks: {
                ...BI_COMBINED_MEASURES_MOCKS,
                post: {
                    ...BI_COMBINED_MEASURES_MOCKS.post,
                    '/api/environments/:team_id/query/HogQLQuery/': {
                        columns: ['bi_row_timestamp', 'sum_revenue', 'bi_comparison'],
                        types: [
                            ['bi_row_timestamp', 'DateTime'],
                            ['sum_revenue', 'Float64'],
                            ['bi_comparison', 'String'],
                        ],
                        results: [
                            ['2026-06-01', 120, 'Current period'],
                            ['2026-06-02', 210, 'Current period'],
                            ['2026-06-03', 180, 'Current period'],
                            ['2026-06-04', 245, 'Current period'],
                            ['2026-06-01', 100, 'Previous period'],
                            ['2026-06-02', 150, 'Previous period'],
                            ['2026-06-03', 120, 'Previous period'],
                            ['2026-06-04', 220, 'Previous period'],
                        ],
                        hasMore: false,
                    },
                },
            },
        },
    },
}

const BI_PIVOT_TOTALS_CONFIG: BIConfig = {
    ...BI_ANALYSIS_CONFIG,
    chartType: ChartDisplayType.TwoDimensionalHeatmap,
    values: [BI_COMBO_CONFIG.values[0]],
    totals: { rows: true, columns: true },
}

export const BIPivotTotals: Story = {
    ...BITableAnalysis,
    parameters: {
        ...BITableAnalysis.parameters,
        pageUrl: `${urls.businessIntelligence()}#${new URLSearchParams({ q: buildBIQuery(BI_PIVOT_TOTALS_CONFIG)!.query, mode: 'bi', bi: JSON.stringify(BI_PIVOT_TOTALS_CONFIG) })}`,
        msw: {
            mocks: {
                ...BI_TABLE_ANALYSIS_MOCKS,
                post: {
                    ...BI_TABLE_ANALYSIS_MOCKS.post,
                    '/api/environments/:team_id/query/HogQLQuery/': {
                        columns: ['bi_row_timestamp', 'bi_column_event', 'sum_revenue'],
                        types: [
                            ['bi_row_timestamp', 'String'],
                            ['bi_column_event', 'String'],
                            ['sum_revenue', 'Float64'],
                        ],
                        results: [
                            ['Total', 'Total', 340],
                            ['Total', 'purchase', 300],
                            ['Total', 'Other', 40],
                            ['2026-06-01', 'Total', 160],
                            ['2026-06-02', 'Total', 180],
                            ['2026-06-01', 'purchase', 120],
                            ['2026-06-02', 'purchase', 180],
                            ['2026-06-01', 'Other', 40],
                        ],
                        hasMore: false,
                    },
                },
            },
        },
    },
}

const BI_GEOGRAPHY_FIELDS: BIField[] = ['Country', 'State', 'City'].map((name) => ({
    ...biEventsField(name, 'string'),
    expression: `properties.${name.toLowerCase()}`,
}))

const BI_HIERARCHY_CONFIG: BIConfig = {
    ...BI_WORKSHEET_CONFIG,
    chartType: ChartDisplayType.ActionsTable,
    rows: [BI_GEOGRAPHY_FIELDS[0]],
    columns: [],
    filters: [],
    hierarchies: [{ id: 'geography', name: 'Geography', levels: BI_GEOGRAPHY_FIELDS }],
}

const BI_HIERARCHY_WORKSHEET = {
    ...buildBIQuery(BI_HIERARCHY_CONFIG)!.node,
    kind: NodeKind.BIVisualizationNode,
    config: BI_HIERARCHY_CONFIG,
}

export const BINamedHierarchy: Story = {
    ...BITableAnalysis,
    parameters: {
        ...BITableAnalysis.parameters,
        pageUrl: `${urls.businessIntelligence()}#q=${encodeURIComponent(JSON.stringify(BI_HIERARCHY_WORKSHEET))}`,
        testOptions: { ...BITableAnalysis.parameters?.testOptions, includeNavigationInSnapshot: true },
        msw: {
            mocks: {
                ...BI_MODE_WORKSHEET_MOCKS,
                get: {
                    ...BI_MODE_WORKSHEET_MOCKS.get,
                    '/api/projects/:team_id/insights/': {
                        results: [
                            {
                                id: 910,
                                short_id: 'exampleGeo',
                                name: 'Example geography',
                                query: BI_HIERARCHY_WORKSHEET,
                            },
                        ],
                        next: null,
                        count: 1,
                    },
                    '/api/projects/:team_id/insights/910/': {
                        id: 910,
                        short_id: 'exampleGeo',
                        name: 'Example geography',
                        query: BI_HIERARCHY_WORKSHEET,
                    },
                },
                post: {
                    ...BI_MODE_WORKSHEET_MOCKS.post,
                    '/api/environments/:team_id/query/DatabaseSchemaQuery/': {
                        tables: {
                            events: {
                                id: 'events',
                                name: 'events',
                                type: 'posthog',
                                fields: {
                                    ...BI_EVENTS_FIELDS,
                                    ...Object.fromEntries(
                                        BI_GEOGRAPHY_FIELDS.map((field) => [
                                            field.name,
                                            {
                                                name: field.name,
                                                hogql_value: field.expression,
                                                type: field.type,
                                                schema_valid: true,
                                            },
                                        ])
                                    ),
                                },
                            },
                        },
                    },
                    '/api/environments/:team_id/query/HogQLQuery/': async ({ request }: MockResolverInfo) => {
                        const { query } = (await request.json()) as { query: { query: string } }
                        const level =
                            BI_GEOGRAPHY_FIELDS.find((field) =>
                                query.query.split('FROM')[0].includes(field.expression)
                            ) ?? BI_GEOGRAPHY_FIELDS[0]
                        const column = getBIResultDimensions({ ...BI_HIERARCHY_CONFIG, rows: [level] })[0].column
                        return [
                            200,
                            {
                                columns: [column, 'sum_revenue'],
                                types: [
                                    [column, 'String'],
                                    ['sum_revenue', 'Float64'],
                                ],
                                results: [[`Example ${level.name.toLowerCase()}`, 120]],
                                hasMore: false,
                            },
                        ]
                    },
                },
            },
        },
    },
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        await userEvent.click(await canvas.findByRole('button', { name: /^Run$/ }))
        await userEvent.click(await canvas.findByText('120', { exact: true }))
        await userEvent.click(
            await within(document.body).findByRole('button', {
                name: 'Geography: filters this worksheet to the selection',
            })
        )
        await userEvent.click(await canvas.findByRole('button', { name: /^Run$/ }))
        await waitFor(() => expect(canvas.getByText('Example state', { exact: true })).toBeVisible())
        await stabilizeQueryElapsedTime()
    },
}

export const BICategoryGroups: Story = {
    ...biWorksheetStory,
    parameters: {
        ...biWorksheetStory.parameters,
        testOptions: { waitForSelector: '[data-attr="bi-local-field-modal"]', viewport: { width: 1050, height: 900 } },
    },
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        await userEvent.click(await canvas.findByLabelText('Options for event', {}, { timeout: 15000 }))
        const body = within(canvasElement.ownerDocument.body)
        await userEvent.click(await body.findByText('Group categories', { exact: true }))
        await userEvent.type(await body.findByLabelText('Group 1 name'), 'Purchases')
    },
}

export const BINumericBins: Story = {
    ...biWorksheetStory,
    parameters: { ...BICategoryGroups.parameters },
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        await userEvent.click(await canvas.findByLabelText('Options for revenue', {}, { timeout: 15000 }))
        const body = within(canvasElement.ownerDocument.body)
        await userEvent.click(await body.findByText('Create numeric bins', { exact: true }))
    },
}

export const BICatalogSource: Story = {
    ...biWorksheetStory,
    parameters: {
        ...biWorksheetStory.parameters,
        msw: {
            mocks: {
                get: {
                    '/api/projects/:team_id/warehouse_expressions/': { results: [] },
                    '/api/projects/:team_id/data_catalog/relationship_proposals/': {
                        count: 1,
                        next: null,
                        results: [
                            {
                                id: 'proposal-example',
                                source_table_name: 'events',
                                source_table_key: 'account_id',
                                joining_table_name: 'accounts',
                                joining_table_key: 'id',
                                field_name: 'account',
                                status: 'proposed',
                                reasoning: 'Connect each event to its account.',
                            },
                        ],
                    },
                },
                post: {
                    '/api/environments/:team_id/query/HogQLQuery/': {
                        columns: [
                            ...getBIResultDimensions(BI_WORKSHEET_CONFIG).map(({ column }) => column),
                            ...getBIResultMeasureColumns(BI_WORKSHEET_CONFIG).map(({ column }) => column),
                        ],
                        types: ['DateTime', 'String', 'Float64'],
                        results: [
                            ['2026-06-01', 'purchase', 120],
                            ['2026-06-02', 'purchase', 180],
                            ['2026-06-03', 'purchase', 150],
                        ],
                        hasMore: false,
                    },
                    '/api/environments/:team_id/query/DatabaseSchemaQuery/': {
                        tables: {
                            events: {
                                id: 'events',
                                name: 'events',
                                type: 'posthog',
                                fields: BI_EVENTS_FIELDS,
                                certification: {
                                    status: 'certified',
                                    notes: 'Use this source for product activity worksheets.',
                                },
                            },
                        },
                        joins: [],
                    },
                },
            },
        },
    },
}

export const BICatalogSnapshot: Story = {
    ...biWorksheetStory,
    parameters: {
        ...biWorksheetStory.parameters,
        pageUrl: `${urls.businessIntelligenceNew()}?metric=weekly_revenue`,
        testOptions: { waitForSelector: '[data-attr="bi-catalog-snapshot"]' },
        msw: {
            mocks: {
                get: {
                    '/api/projects/:team_id/data_catalog/metrics/weekly_revenue/': {
                        name: 'weekly_revenue',
                        display_name: 'Weekly revenue',
                        definition: {
                            kind: NodeKind.HogQLQuery,
                            query: "SELECT sum(revenue) AS revenue FROM events WHERE timestamp >= toDateTime('2026-06-01') AND timestamp < toDateTime('2026-06-08')",
                        },
                    },
                    '/api/projects/:team_id/warehouse_expressions/': { results: [] },
                },
                post: {
                    '/api/environments/:team_id/query/HogQLQuery/': {
                        columns: ['revenue'],
                        types: ['Float64'],
                        results: [[450]],
                        hasMore: false,
                    },
                },
            },
        },
    },
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        await canvas.findByRole('link', { name: 'View current catalog entry' }, { timeout: 15000 })
        await userEvent.click(await canvas.findByRole('button', { name: 'Run worksheet' }))
        await expect(canvas.findByText('450', { exact: true })).resolves.toBeVisible()
    },
}

export const BISourcePreviewLargeSample: Story = {
    ...biWorksheetStory,
    parameters: {
        ...biWorksheetStory.parameters,
        msw: {
            mocks: {
                ...BI_MODE_WORKSHEET_MOCKS,
                get: {
                    ...BI_MODE_WORKSHEET_MOCKS.get,
                    '/api/projects/:team_id/data_catalog/relationship_proposals/': {
                        count: 0,
                        next: null,
                        results: [],
                    },
                },
                post: {
                    ...BI_MODE_WORKSHEET_MOCKS.post,
                    '/api/projects/:team_id/file_system/home_folder/': { id: 'example-home', path: 'Users/Example' },
                    '/api/environments/:team_id/query/HogQLQuery/': async ({ request }: MockResolverInfo) => {
                        const { query } = (await request.json()) as { query: { query: string } }
                        if (query.query.startsWith('SELECT *')) {
                            const limit = Number(query.query.match(/LIMIT (\d+)/)?.[1] ?? 1000)
                            return {
                                columns: [
                                    'row_number',
                                    'description',
                                    ...Array.from({ length: 8 }, (_, index) => `quantity_${index + 1}`),
                                ],
                                types: [
                                    ['row_number', 'Int64'],
                                    ['description', 'String'],
                                    ...Array.from({ length: 8 }, (_, index) => [`quantity_${index + 1}`, 'Int64']),
                                ],
                                results: Array.from({ length: limit }, (_, index) => [
                                    index + 1,
                                    `Example source row ${index + 1}`,
                                    ...Array.from({ length: 8 }, (_, column) => (index + column) % 17),
                                ]),
                                hasMore: false,
                            }
                        }
                        return {
                            columns: [
                                ...getBIResultDimensions(BI_WORKSHEET_CONFIG).map(({ column }) => column),
                                ...getBIResultMeasureColumns(BI_WORKSHEET_CONFIG).map(({ column }) => column),
                            ],
                            types: ['DateTime', 'String', 'Float64'],
                            results: [['2026-06-01', 'purchase', 120]],
                            hasMore: false,
                        }
                    },
                },
            },
        },
    },
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        const openPreview = await canvas.findByText('View source data', {}, { timeout: 15000 })
        await waitFor(() => expect(openPreview.closest('button')).toHaveAttribute('aria-disabled', 'false'), {
            timeout: 15000,
        })
        await userEvent.click(openPreview)
        const body = within(canvasElement.ownerDocument.body)
        await body.findByText('Example source row 1', {}, { timeout: 15000 })
        const table = canvasElement.ownerDocument.querySelector<HTMLElement>('[data-attr="bi-source-preview-table"]')!
        expect(table.querySelectorAll('tbody tr[data-row-key]').length).toBeLessThan(50)
        const scroll = table.querySelector<HTMLElement>('.ScrollableShadows__inner')!
        scroll.scrollTop = scroll.scrollHeight
        await body.findByText('Example source row 500')
        await userEvent.click(within(table).getByLabelText('Next page'))
        await body.findByText('Example source row 501')
        expect(scroll.scrollTop).toBe(0)
        expect(table.querySelectorAll('tbody tr[data-row-key]').length).toBeLessThan(50)
        scroll.scrollTop = scroll.scrollHeight
        await body.findByText('Example source row 1000')
        await userEvent.click(within(table).getByLabelText('Previous page'))
        await body.findByText('Example source row 1')
    },
}

const BI_WIDE_TABLE_CONFIG: BIConfig = {
    ...BI_WORKSHEET_CONFIG,
    chartType: ChartDisplayType.ActionsTable,
    rows: [{ ...biEventsField('timestamp', 'datetime'), dateBucket: 'day' }],
    columns: [],
    values: [{ field: biEventsField('revenue', 'float'), aggregation: 'sum', shelf: 'rows' }],
    filters: [],
    limit: 10000,
}

export const BIWideTransposedResults: Story = {
    ...biWorksheetStory,
    parameters: {
        ...biWorksheetStory.parameters,
        pageUrl: `${urls.businessIntelligenceNew()}#${new URLSearchParams({
            q: JSON.stringify({
                ...buildBIQuery(BI_WIDE_TABLE_CONFIG)!.node,
                kind: NodeKind.BIVisualizationNode,
                config: BI_WIDE_TABLE_CONFIG,
            }),
        })}`,
        testOptions: {
            waitForSelector: '.DataVisualizationTable [aria-colcount="1801"]',
            viewport: { width: 1280, height: 900 },
        },
        msw: {
            mocks: {
                ...BI_MODE_WORKSHEET_MOCKS,
                get: {
                    ...BI_MODE_WORKSHEET_MOCKS.get,
                    '/api/projects/:team_id/data_catalog/relationship_proposals/': {
                        count: 0,
                        next: null,
                        results: [],
                    },
                },
                post: {
                    ...BI_MODE_WORKSHEET_MOCKS.post,
                    '/api/projects/:team_id/file_system/home_folder/': { id: 'example-home', path: 'Users/Example' },
                    '/api/environments/:team_id/query/HogQLQuery/': {
                        columns: [
                            ...getBIResultDimensions(BI_WIDE_TABLE_CONFIG).map(({ column }) => column),
                            ...getBIResultMeasureColumns(BI_WIDE_TABLE_CONFIG).map(({ column }) => column),
                        ],
                        types: ['DateTime', 'Float64'],
                        results: Array.from({ length: 1800 }, (_, index) => [
                            new Date(Date.UTC(2020, 0, index + 1)).toISOString(),
                            10000 + index,
                        ]),
                        hasMore: false,
                    },
                },
            },
        },
    },
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        await userEvent.click(await canvas.findByRole('button', { name: /^Run$/ }))
        await canvas.findByText('10000', { exact: true }, { timeout: 15000 })
        await userEvent.click(await canvas.findByRole('button', { name: 'Visualization settings' }))
        const transpose = await canvas.findByLabelText('Transpose results')
        await userEvent.click(transpose)
        const table = canvasElement.querySelector<HTMLElement>('.DataVisualizationTable')!
        await waitFor(() => expect(table.querySelector('table')).toHaveAttribute('aria-colcount', '1801'))
        expect(table.querySelectorAll('tbody td:not([aria-hidden])').length).toBeLessThan(40)
        const scroll = table.querySelector<HTMLElement>('.ScrollableShadows__inner')!
        scroll.scrollLeft = scroll.scrollWidth
        await within(table).findByText('11799', { exact: true })
        expect(table.querySelectorAll('tbody td:not([aria-hidden])').length).toBeLessThan(40)
        await userEvent.click(transpose)
        await waitFor(() => expect(table.querySelector('table')).not.toHaveAttribute('aria-colcount'))
        await within(table).findByText('10000', { exact: true })
        await userEvent.click(transpose)
        scroll.scrollLeft = 0
        await within(table).findByText('10000', { exact: true })
        await userEvent.click(canvas.getByRole('button', { name: 'Visualization settings' }))
        await stabilizeQueryElapsedTime()
    },
}

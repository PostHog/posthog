import { Meta, StoryObj } from '@storybook/react'
import { waitFor } from '@testing-library/dom'
import { useEffect } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { BIConfig, BIField, BIVisualizationNode } from '~/queries/schema/schema-business-intelligence'
import { ChartSettings, NodeKind, TableSettings } from '~/queries/schema/schema-general'
import { ChartDisplayType, AccessControlResourceType, AccessControlLevel } from '~/types'

import { expect, userEvent } from 'storybook/test'

import { buildBIQuery, getBIResultDimensions, getBIResultMeasureColumns } from './biEditorTypes'
import { biSceneLogic } from './biSceneLogic'
import { BusinessIntelligenceScene } from './BusinessIntelligenceScene'

const field = (name: string, type: BIField['type'] = 'string'): BIField => ({
    id: name,
    name,
    expression: name === 'Order date' ? '"Order date"' : name,
    type,
    source: { table: 'example_orders' },
})
const region = field('region')
const city = field('city')
const config: BIConfig = {
    source: region.source,
    chartType: ChartDisplayType.ActionsBar,
    limit: 1000,
    rows: [region],
    columns: [],
    values: [{ field: field('revenue', 'float'), aggregation: 'sum' }],
    filters: [
        { field: field('channel'), label: 'Sales channel', operator: 'in', values: ['direct', 'partner'], value: '' },
    ],
    hierarchies: [{ id: 'geography', name: 'Geography', levels: [region, city] }],
    memberAliases: [{ field: region, aliases: [{ value: 'east', label: 'East region' }] }],
    dateRange: { date_from: 'all' },
}
const tabId = 'bi-exploration-story'

function WorksheetStage({
    config,
    width = 1200,
    sqlPreview = false,
    chartSettings,
    tableSettings,
}: {
    config: BIConfig
    width?: number
    sqlPreview?: boolean
    chartSettings?: ChartSettings
    tableSettings?: TableSettings
}): JSX.Element {
    useEffect(() => {
        const logic = biSceneLogic({ tabId })
        const unmount = logic.mount()
        const node: BIVisualizationNode = {
            ...buildBIQuery(config)!.node,
            kind: NodeKind.BIVisualizationNode,
            config,
            chartSettings: { ...buildBIQuery(config)!.node.chartSettings, ...chartSettings },
            tableSettings: { ...buildBIQuery(config)!.node.tableSettings, ...tableSettings },
        }
        logic.actions.restoreWorksheet(node)
        logic.actions.recordWorksheet(true)
        if (sqlPreview) {
            logic.actions.setSqlPreviewOpen(true)
        }
        return unmount
    }, [config, sqlPreview, chartSettings, tableSettings])
    return (
        <div className="h-[850px] max-w-full" style={{ width }}>
            <BusinessIntelligenceScene tabId={tabId} />
        </div>
    )
}

const meta: Meta = {
    title: 'Products/Business intelligence/Worksheet exploration',
    play: async () => {
        await waitFor(() => {
            const { dataNodeKey } = biSceneLogic({ tabId }).values
            const logic = dataNodeLogic.findMounted({ key: dataNodeKey })
            expect(logic?.values.responseLoading).toBe(false)
            expect(logic?.values.response).toBeTruthy()
        })
        const { dataNodeKey } = biSceneLogic({ tabId }).values
        // Mocked responses still measure real browser time, which varies between snapshots.
        dataNodeLogic.findMounted({ key: dataNodeKey })!.actions.setElapsedTime(180)
    },
    beforeEach: () => {
        const context = window.POSTHOG_APP_CONTEXT!
        const previous = context.resource_access_control
        context.resource_access_control = {
            ...previous,
            [AccessControlResourceType.WarehouseObjects]: AccessControlLevel.Editor,
        }
        return () => {
            context.resource_access_control = previous
        }
    },
    parameters: {
        layout: 'centered',
        featureFlags: [FEATURE_FLAGS.SQL_EDITOR_BI_MODE],
        testOptions: { waitForSelector: '[data-attr="bi-result-summary"]' },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/insights/': { count: 0, results: [] },
                '/api/projects/:team_id/data_catalog/relationship_proposals/': { results: [], next: null },
                '/api/projects/:team_id/warehouse_column_annotations/': { results: [] },
                '/api/projects/:team_id/warehouse_saved_queries/': { results: [] },
                '/api/projects/:team_id/external_data_sources/connections/': [],
                '/api/projects/:team_id/external_data_sources/direct_connection_options/': [],
            },
            post: {
                '/api/projects/:team_id/query/HogQLMetadata/': {
                    isValid: true,
                    errors: [],
                    warnings: [],
                    notices: [],
                    output_columns: [{ name: 'value', type: 'Float64' }],
                },
                '/api/environments/:team_id/query/:query_kind/': async ({ request }) => {
                    const { query } = (await request.json()) as {
                        query: { kind: string; query?: string; limit?: number }
                    }
                    if (query.kind === NodeKind.HogQLAutocomplete) {
                        return [200, { suggestions: [] }]
                    }
                    if (query.kind === NodeKind.HogQLMetadata) {
                        return [
                            200,
                            {
                                isValid: true,
                                errors: [],
                                warnings: [],
                                notices: [],
                                output_columns: [
                                    { name: 'value', type: query.query?.includes('revenue') ? 'Float64' : 'String' },
                                ],
                            },
                        ]
                    }
                    if (query.kind === NodeKind.DatabaseSchemaQuery) {
                        const fields = [
                            region,
                            city,
                            field('channel'),
                            field('item'),
                            field('revenue', 'float'),
                            field('cost', 'float'),
                            field('Order date', 'datetime'),
                        ]
                        return [
                            200,
                            {
                                joins: [
                                    {
                                        id: 'example-order-account',
                                        source_table_name: 'example_orders',
                                        source_table_key: 'account_id',
                                        joining_table_name: 'example_accounts',
                                        joining_table_key: 'id',
                                        field_name: 'account',
                                    },
                                ],
                                tables: {
                                    example_legacy_orders: {
                                        id: 'example_legacy_orders',
                                        name: 'example_legacy_orders',
                                        type: 'data_warehouse',
                                        fields: {},
                                        certification: {
                                            status: 'deprecated',
                                            notes: 'Use example_orders for new worksheets.',
                                        },
                                    },
                                    example_raw_orders: {
                                        id: 'example_raw_orders',
                                        name: 'example_raw_orders',
                                        type: 'data_warehouse',
                                        fields: {},
                                    },
                                    example_orders: {
                                        certification: { status: 'certified', notes: 'Reviewed example order totals.' },
                                        id: 'example_orders',
                                        name: 'example_orders',
                                        type: 'data_warehouse',
                                        fields: Object.fromEntries(
                                            fields.map((field) => [
                                                field.name,
                                                { name: field.name, type: field.type, schema_valid: true },
                                            ])
                                        ),
                                    },
                                },
                            },
                        ]
                    }
                    if (query.query?.includes('bi_filter_values')) {
                        return [
                            200,
                            {
                                columns: ['value'],
                                types: [['value', 'String']],
                                results: ['east', 'west', 'north', 'south', ''].map((value) => [value]),
                            },
                        ]
                    }
                    if (query.query?.startsWith('SELECT *')) {
                        return [
                            200,
                            {
                                columns: ['item', 'region', 'revenue', 'cost'],
                                types: [
                                    ['item', 'String'],
                                    ['region', 'String'],
                                    ['revenue', 'Float64'],
                                    ['cost', 'Float64'],
                                ],
                                results: [
                                    ['Example item', 'east', 30, 12],
                                    ['Example item', 'east', 20, 8],
                                    ['Another item', 'west', 10, 3],
                                ],
                            },
                        ]
                    }
                    const worksheet = biSceneLogic({ tabId }).values.lastRunQuery
                    const current = worksheet?.config ?? config
                    const dimensions = getBIResultDimensions(current)
                    const measures = getBIResultMeasureColumns(current)
                    const daily = dimensions.some(({ field }) => field.dateBucket === 'day')
                    const columns = [...dimensions.map(({ column }) => column), ...measures.map(({ column }) => column)]
                    const limit = Number(query.query?.match(/LIMIT (\d+)\s*$/)?.[1] ?? 1000)
                    const results = Array.from(
                        { length: Math.min(current.panes ? 16 : daily ? 1500 : 4, limit) },
                        (_, index) => [
                            ...dimensions.map(({ field }) =>
                                field.dateBucket === 'year'
                                    ? `${2024 + Math.floor(index / 8)}-01-01T00:00:00Z`
                                    : field.datePart === 'quarter'
                                      ? Math.floor((index % 8) / 2) + 1
                                      : field.dateBucket === 'day'
                                        ? new Date(Date.UTC(2022, 0, index + 1)).toISOString()
                                        : current.panes
                                          ? ['east', 'west'][index % 2]
                                          : ['east', 'west', 'north', 'south'][index % 4]
                            ),
                            ...measures.map((_, measure) => 20 + ((index * 7 + measure * 13) % 90)),
                        ]
                    )
                    return [
                        200,
                        {
                            columns,
                            types: [
                                ...dimensions.map(({ column, field }) => [
                                    column,
                                    field.datePart ? 'Int64' : field.type === 'datetime' ? 'DateTime' : 'String',
                                ]),
                                ...measures.map(({ column }) => [column, 'Float64']),
                            ],
                            results,
                        },
                    ]
                },
            },
        }),
    ],
}
export default meta

export const RelationshipKeyCheck: StoryObj = {
    render: () => <WorksheetStage config={config} />,
    play: async () => {
        await userEvent.click(
            await waitFor(() => {
                const summary = document.querySelector('[data-attr="bi-source-context"] summary')
                expect(summary).toBeTruthy()
                return summary as HTMLElement
            })
        )
    },
}

export const FiltersAndHierarchy: StoryObj = { render: () => <WorksheetStage config={config} /> }
export const Narrow: StoryObj = { render: () => <WorksheetStage config={config} width={520} /> }
export const SQLPreview: StoryObj = { render: () => <WorksheetStage config={config} sqlPreview /> }
const tableConfig: BIConfig = { ...config, chartType: ChartDisplayType.ActionsTable }
const tableSettings: TableSettings = {
    conditionalFormatting: [
        {
            id: 'revenue-highlight',
            templateId: 'equals',
            columnName: getBIResultMeasureColumns(tableConfig)[0].column,
            input: '27',
            color: '#FFADAD',
            colorMode: 'light',
            bytecode: ['_H', 1, 32, 'input', 1, 1, 32, 'value', 1, 1, 11, 38],
        },
    ],
}
export const TableConditionalFormatting: StoryObj = {
    render: () => <WorksheetStage config={tableConfig} tableSettings={tableSettings} />,
    play: async (context) => {
        await meta.play?.(context)
        const button = context.canvasElement.querySelector('[data-attr="bi-conditional-formatting"]')
        expect(button).toBeTruthy()
        await userEvent.click(button!)
        await waitFor(() => expect(context.canvasElement.querySelector('.ConditionalFormattingTab')).toBeTruthy())
        await waitFor(() => expect(context.canvasElement.querySelector('td[style*="background-color"]')).toBeTruthy())
    },
}
const dailyConfig: BIConfig = {
    ...config,
    chartType: ChartDisplayType.ActionsLineGraph,
    limit: 50000,
    rows: [{ ...field('Order date', 'datetime'), dateBucket: 'day' }],
    filters: [],
}
export const Daily1500Groups: StoryObj = { render: () => <WorksheetStage config={dailyConfig} /> }

const scatterConfig: BIConfig = {
    ...config,
    chartType: ChartDisplayType.ScatterPlot,
    rows: [field('item'), region],
    values: [
        { field: field('revenue', 'float'), aggregation: 'sum' },
        { field: field('cost', 'float'), aggregation: 'sum' },
    ],
    colorBy: 'region',
}
export const ScatterSelection: StoryObj = { render: () => <WorksheetStage config={scatterConfig} /> }

const year = { ...field('Order date', 'datetime'), id: 'order-year', dateBucket: 'year' as const }
const quarter = { ...field('Order date', 'datetime'), id: 'order-quarter', datePart: 'quarter' as const }
const paneConfig: BIConfig = {
    ...config,
    rows: [year],
    columns: [quarter, region],
    filters: [],
    colorBy: region.id,
    panes: { fields: [year.id] },
}
const paneSettings: ChartSettings = { goalLines: [{ label: 'Pane average', value: 0, calculation: 'mean' }] }
export const NestedPanes: StoryObj = {
    render: () => <WorksheetStage config={paneConfig} chartSettings={paneSettings} />,
}
export const NestedPanesNarrow: StoryObj = {
    render: () => <WorksheetStage config={paneConfig} chartSettings={paneSettings} width={520} />,
}

export const CatalogMetricParameters: StoryObj = {
    parameters: { testOptions: { waitForSelector: '[role="dialog"]' } },
    render: () => (
        <WorksheetStage
            config={{
                ...config,
                source: null,
                catalogMetric: 'regional_revenue',
                querySnapshot: {
                    kind: NodeKind.HogQLQuery,
                    query: 'SELECT region, sum(revenue) AS revenue FROM example_orders WHERE channel = {channel} AND revenue >= {minimum_revenue} GROUP BY region',
                    values: { channel: 'direct', minimum_revenue: 100 },
                },
            }}
        />
    ),
    play: async (context) => {
        await meta.play?.(context)
        await userEvent.click(
            await waitFor(() => {
                const button = Array.from(document.querySelectorAll('button')).find(
                    (button) => button.textContent === 'Edit parameters'
                )
                expect(button).toBeTruthy()
                return button!
            })
        )
    },
}

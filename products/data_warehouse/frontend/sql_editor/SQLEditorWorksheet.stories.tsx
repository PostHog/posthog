import { Meta } from '@storybook/react'
import { waitFor, within } from '@testing-library/dom'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { BIConfig } from '~/queries/schema/schema-business-intelligence'
import { NodeKind } from '~/queries/schema/schema-general'
import type { InsightShortId } from '~/types'
import { ChartDisplayType } from '~/types'

import { buildBIQuery } from 'products/business_intelligence/frontend/biEditorTypes'

import { expect, userEvent } from 'storybook/test'

import {
    biEventsField,
    BI_WORKSHEET_CONFIG,
    BI_EVENTS_FIELDS,
    Story,
    DISCARD_INSIGHT,
    BI_MODE_WORKSHEET_MOCKS,
    biWorksheetStory,
    sqlEditorStoryMeta,
} from './__mocks__/SQLEditorStoryFixtures'

const meta: Meta = { ...sqlEditorStoryMeta, component: App, title: 'Scenes-App/Data Warehouse/SQL Editor' }
export default meta

export const BIEmptyWorksheet: Story = {
    ...biWorksheetStory,
    parameters: {
        ...biWorksheetStory.parameters,
        // An explicit empty query prevents restoring another story's persisted worksheet.
        pageUrl: `${urls.businessIntelligence()}#q=`,
        testOptions: { waitForSelector: '[data-attr="bi-editor-data-source"]' },
    },
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        await expect(canvas.findByText('Select a table to list its fields.')).resolves.toBeVisible()
        await userEvent.click(canvas.getByRole('button', { name: 'Hide fields panel' }))
        expect(canvas.queryByText('Select a table to list its fields.')).not.toBeInTheDocument()
        await userEvent.click(canvas.getByRole('button', { name: /^Fields$/ }))
        await expect(canvas.findByText('Select a table to list its fields.')).resolves.toBeVisible()
    },
}

const BI_SAVED_QUERY = {
    ...buildBIQuery(BI_WORKSHEET_CONFIG)!.node,
    kind: NodeKind.BIVisualizationNode as const,
    config: BI_WORKSHEET_CONFIG,
}
BI_SAVED_QUERY.chartSettings!.yAxis![0].settings = { formatting: { prefix: '$', suffix: '' } }
BI_SAVED_QUERY.tableSettings = {
    columns: ['bi_row_timestamp', 'bi_column_event', 'sum_revenue'].map((column) => ({
        column,
        settings: { formatting: { prefix: '', suffix: '' } },
    })),
}

const BI_SAVED_INSIGHT = {
    ...DISCARD_INSIGHT,
    short_id: 'bisaved1',
    name: 'Revenue by event',
    query: BI_SAVED_QUERY,
}

export const BISavedInsight: Story = {
    ...biWorksheetStory,
    parameters: {
        ...biWorksheetStory.parameters,
        pageUrl: urls.insightView('bisaved1' as InsightShortId),
        testOptions: { waitForSelector: '[data-attr="insight-edit-button"]', viewport: { width: 1600, height: 900 } },
        msw: {
            mocks: {
                ...BI_MODE_WORKSHEET_MOCKS,
                get: {
                    ...BI_MODE_WORKSHEET_MOCKS.get,
                    '/api/:scope/:team_id/insights/': [200, { results: [BI_SAVED_INSIGHT] }],
                    '/api/environments/:team_id/insights/:id/': [200, BI_SAVED_INSIGHT],
                    '/api/projects/:team_id/events_retention/': [200, { retention_months: null, retained_from: null }],
                },
            },
        },
    },
}

export const BIEditSavedInsight: Story = {
    ...BISavedInsight,
    parameters: {
        ...BISavedInsight.parameters,
        pageUrl: urls.businessIntelligence({ insightShortId: 'bisaved1' }),
        testOptions: biWorksheetStory.parameters?.testOptions,
    },
    play: async ({ canvasElement }) => {
        await waitFor(() =>
            expect(canvasElement.querySelector('[data-attr="bi-editor-data-pane-measure"]')).not.toBeNull()
        )
        await waitFor(() =>
            expect(within(canvasElement).queryByText('Edited', { exact: true })).not.toBeInTheDocument()
        )
    },
}

export const BICalculatedMeasureEditor: Story = {
    ...biWorksheetStory,
    parameters: {
        ...biWorksheetStory.parameters,
        testOptions: {
            waitForSelector: '[data-attr="bi-calculated-measure-modal"] .monaco-editor',
            viewport: { width: 1050, height: 900 },
        },
        msw: {
            mocks: {
                ...BI_MODE_WORKSHEET_MOCKS,
                post: {
                    ...BI_MODE_WORKSHEET_MOCKS.post,
                    '/api/projects/:team_id/query/HogQLAutocomplete/': {
                        suggestions: [{ kind: 'Variable', label: 'event', insertText: 'event', detail: 'String' }],
                        incomplete_list: false,
                    },
                },
            },
        },
    },
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        const addMeasure = await canvas.findByRole('button', { name: 'Add calculated field' }, { timeout: 15000 })
        await waitFor(() => expect(addMeasure).toBeEnabled())
        await userEvent.click(addMeasure)
        const modal = within(canvasElement.ownerDocument.body)
        await userEvent.click(await modal.findByLabelText('Calculated field role'))
        await userEvent.click(await modal.findByText('Measure · aggregate each group'))
        await userEvent.type(await modal.findByLabelText('Name'), 'ARPU')
        const expression = await modal.findByRole('textbox', { name: 'Calculated field expression' })
        expression.focus()
        // Monaco resolves keybindings from keyCode, and userEvent.keyboard sends keyCode 0
        const pressInEditor = (init: KeyboardEventInit & { keyCode: number }): void => {
            expression.dispatchEvent(new KeyboardEvent('keydown', { ...init, bubbles: true, cancelable: true }))
        }
        pressInEditor({ key: ' ', code: 'Space', keyCode: 32, ctrlKey: true })
        await waitFor(
            () => {
                const suggestions = canvasElement.ownerDocument.querySelector('.suggest-widget.visible')
                expect(suggestions).not.toBeNull()
                expect(within(suggestions as HTMLElement).getByText('event', { exact: true })).toBeVisible()
            },
            { timeout: 5000 }
        )
        // A keyCode 0 Escape skips Monaco and reaches the modal, which then closes
        pressInEditor({ key: 'Escape', code: 'Escape', keyCode: 27 })
        await waitFor(() => expect(canvasElement.ownerDocument.querySelector('.suggest-widget.visible')).toBeNull())
    },
}

const BI_QUICK_FILTERS_CONFIG: BIConfig = {
    ...BI_WORKSHEET_CONFIG,
    chartType: ChartDisplayType.ActionsTable,
    columns: [],
    values: [
        {
            field: biEventsField('revenue', 'float'),
            aggregation: 'custom',
            label: 'ARPU',
            customExpression: 'sum(revenue) / nullIf(count(DISTINCT user_id), 0)',
        },
    ],
    filters: [
        { field: biEventsField('event', 'string'), operator: 'in', value: '', values: ['purchase', 'renewal'] },
        {
            field: biEventsField('timestamp', 'datetime'),
            operator: 'between',
            value: '2026-06-01 00:00:00',
            valueTo: '2026-06-07 23:59:59',
        },
    ],
}

export const BIQuickFilters: Story = {
    ...biWorksheetStory,
    parameters: {
        ...biWorksheetStory.parameters,
        pageUrl: `${urls.businessIntelligence()}#${new URLSearchParams({ q: buildBIQuery(BI_QUICK_FILTERS_CONFIG)?.query ?? '', mode: 'bi', bi: JSON.stringify(BI_QUICK_FILTERS_CONFIG) })}`,
        msw: {
            mocks: {
                ...BI_MODE_WORKSHEET_MOCKS,
                post: {
                    ...BI_MODE_WORKSHEET_MOCKS.post,
                    '/api/environments/:team_id/query/HogQLQuery/': async ({ request }: { request: Request }) => {
                        const { query } = await request.json()
                        return [
                            200,
                            query.query.startsWith('SELECT DISTINCT')
                                ? {
                                      columns: ['value'],
                                      types: ['String'],
                                      results: [['purchase'], ['renewal'], ['refund'], ['trial_started']],
                                      hasMore: false,
                                  }
                                : {
                                      columns: ['toStartOfDay(timestamp)', 'ARPU'],
                                      types: ['DateTime', 'Float64'],
                                      hasMore: false,
                                      results: [24, 28, 26, 31, 35, 33, 38].map((value, index) => [
                                          `2026-06-0${index + 1} 00:00:00`,
                                          value,
                                      ]),
                                  },
                        ]
                    },
                },
            },
        },
    },
}

export const BIQuickFiltersNarrow: Story = {
    ...BIQuickFilters,
    parameters: {
        ...BIQuickFilters.parameters,
        pageUrl: `${urls.businessIntelligence()}#${new URLSearchParams({
            mode: 'bi',
            bi: JSON.stringify({
                ...BI_QUICK_FILTERS_CONFIG,
                filters: [
                    ...BI_QUICK_FILTERS_CONFIG.filters,
                    {
                        field: biEventsField('properties.region', 'string'),
                        operator: 'in',
                        value: '',
                        values: ['North', 'West'],
                    },
                    {
                        field: biEventsField('properties.device', 'string'),
                        operator: 'in',
                        value: '',
                        values: ['Desktop'],
                    },
                    {
                        field: biEventsField('properties.channel', 'string'),
                        operator: 'not_in',
                        value: '',
                        values: ['Internal'],
                    },
                    { field: biEventsField('revenue', 'float'), operator: 'between', value: '0', valueTo: '1000' },
                    { field: biEventsField('duration_ms', 'integer'), operator: 'less_than', value: '5000' },
                    { field: biEventsField('distinct_id', 'string'), operator: 'is_set', value: '' },
                ],
            } satisfies BIConfig),
        })}`,
        testOptions: {
            waitForSelector: '[data-attr="bi-editor-filters-pill"]',
            viewport: { width: 1050, height: 900 },
        },
    },
}

export const BIDataSourcePicker: Story = {
    ...biWorksheetStory,
    parameters: {
        ...biWorksheetStory.parameters,
        testOptions: {
            waitForSelector: '[data-attr="bi-editor-data-source-picker"]',
            viewport: { width: 1280, height: 800 },
        },
        msw: {
            mocks: {
                ...BI_MODE_WORKSHEET_MOCKS,
                post: {
                    ...BI_MODE_WORKSHEET_MOCKS.post,
                    '/api/environments/:team_id/query/DatabaseSchemaQuery/': {
                        tables: {
                            events: { id: 'events', name: 'events', type: 'posthog', fields: BI_EVENTS_FIELDS },
                            persons: { id: 'persons', name: 'persons', type: 'posthog', fields: {} },
                            stripe_customers: {
                                id: 'stripe_customers',
                                name: 'stripe_customers',
                                type: 'data_warehouse',
                                fields: {},
                                source: { id: 'example-stripe', source_type: 'Stripe', prefix: 'stripe_' },
                            },
                            stripe_invoices: {
                                id: 'stripe_invoices',
                                name: 'stripe_invoices',
                                type: 'data_warehouse',
                                fields: {},
                                source: { id: 'example-stripe', source_type: 'Stripe', prefix: 'stripe_' },
                            },
                            postgres_orders: {
                                id: 'postgres_orders',
                                name: 'postgres_orders',
                                type: 'data_warehouse',
                                fields: {},
                                source: { id: 'example-postgres', source_type: 'Postgres', prefix: 'postgres_' },
                            },
                        },
                    },
                },
            },
        },
    },
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        await waitFor(() => expect(canvasElement.querySelector('[data-attr="bi-editor-data-source"]')).toBeVisible(), {
            timeout: 15000,
        })
        await waitFor(() => expect(canvas.queryByText('Locate')).not.toBeInTheDocument())
        await userEvent.click(canvasElement.querySelector('[data-attr="bi-editor-data-source"]')!)
        const page = within(canvasElement.ownerDocument.body)
        await waitFor(() => expect(page.getByRole('searchbox', { name: 'Search tables' })).toBeVisible())
    },
}

const BI_CONNECTIONS_CONFIG: BIConfig = {
    ...BI_WORKSHEET_CONFIG,
    chartType: ChartDisplayType.ActionsTable,
    rows: [],
    columns: [],
    filters: [],
}

export const BIConnections: Story = {
    ...biWorksheetStory,
    parameters: {
        ...biWorksheetStory.parameters,
        pageUrl: `${urls.businessIntelligence()}#${new URLSearchParams({
            q: buildBIQuery(BI_CONNECTIONS_CONFIG)?.query ?? '',
            mode: 'bi',
            bi: JSON.stringify(BI_CONNECTIONS_CONFIG),
        })}`,
        testOptions: {
            waitForSelector: '[data-attr="bi-editor-connection-fields"] [data-attr="bi-editor-connection-fields"]',
            viewport: { width: 1280, height: 900 },
        },
        msw: {
            mocks: {
                ...BI_MODE_WORKSHEET_MOCKS,
                post: {
                    ...BI_MODE_WORKSHEET_MOCKS.post,
                    '/api/environments/:team_id/query/DatabaseSchemaQuery/': {
                        tables: {
                            events: {
                                id: 'events',
                                name: 'events',
                                type: 'posthog',
                                fields: {
                                    event: BI_EVENTS_FIELDS.event,
                                    revenue: BI_EVENTS_FIELDS.revenue,
                                    person: {
                                        name: 'person',
                                        type: 'lazy_table',
                                        table: 'persons',
                                        schema_valid: true,
                                        hogql_value: 'person',
                                    },
                                },
                            },
                            persons: {
                                id: 'persons',
                                name: 'persons',
                                type: 'posthog',
                                fields: {
                                    email: { name: 'email', type: 'string', schema_valid: true, hogql_value: 'email' },
                                    lifetime_value: {
                                        name: 'lifetime_value',
                                        type: 'float',
                                        schema_valid: true,
                                        hogql_value: 'lifetime_value',
                                    },
                                    company: {
                                        name: 'company',
                                        type: 'lazy_table',
                                        table: 'companies',
                                        schema_valid: true,
                                        hogql_value: 'company',
                                    },
                                },
                            },
                            companies: {
                                id: 'companies',
                                name: 'companies',
                                type: 'data_warehouse',
                                fields: {
                                    name: { name: 'name', type: 'string', schema_valid: true, hogql_value: 'name' },
                                    annual_revenue: {
                                        name: 'annual_revenue',
                                        type: 'decimal',
                                        schema_valid: true,
                                        hogql_value: 'annual_revenue',
                                    },
                                },
                            },
                        },
                    },
                },
            },
        },
    },
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        await waitFor(() => expect(canvasElement.querySelector('[data-attr="bi-editor-data-source"]')).toBeVisible(), {
            timeout: 15000,
        })
        const autoUpdate = canvasElement.querySelector('[data-attr="bi-editor-auto-update"]')!
        if (autoUpdate.getAttribute('aria-checked') === 'true') {
            await userEvent.click(autoUpdate)
        }
        await userEvent.click(await canvas.findByRole('button', { name: 'person' }))
        await userEvent.click(await canvas.findByRole('button', { name: 'person.company' }))
        await waitFor(() => expect(canvas.getByText('annual_revenue')).toBeVisible())
    },
}

export const BIModeWorksheet: Story = biWorksheetStory

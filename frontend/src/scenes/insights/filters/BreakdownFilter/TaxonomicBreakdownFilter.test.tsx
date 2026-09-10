import '@testing-library/jest-dom'

import { cleanup, configure, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { NodeKind, TrendsQuery } from '~/queries/schema/schema-general'
import { buildTrendsQuery, renderInsightPage } from '~/test/insight-testing'

// The disabled-reason copy shows through LemonButton's Tooltip, which has a 400ms open
// delay. On contended CI shards that delay plus jsdom positioning can exceed the default
// 1s waitFor budget, so the hover assertions flake. Give them room (and raise the per-test
// timeout to match, so a single waitFor can't exhaust the 5s default test budget).
configure({ asyncUtilTimeout: 5000 })
jest.setTimeout(15000)

// Monaco does not render under jsdom, and the SQL expression tab mounts it eagerly.
jest.mock('lib/monaco/CodeEditorInline', () => ({
    CodeEditorInline: (): JSX.Element => <textarea aria-label="SQL expression" />,
}))

jest.mock('lib/components/AutoSizer', () => ({
    AutoSizer: ({ renderProp }: { renderProp: (size: { height: number; width: number }) => React.ReactNode }) =>
        renderProp({ height: 400, width: 400 }),
}))

async function waitForBreakdownButton(): Promise<HTMLElement> {
    return waitFor(() => {
        const button = screen.getByTestId('add-breakdown-button')
        expect(button).toBeInTheDocument()
        return button
    })
}

describe('TaxonomicBreakdownFilter', () => {
    afterEach(cleanup)

    describe('not at cap', () => {
        it('renders the + Breakdown button as enabled when no breakdowns are set', async () => {
            renderInsightPage({ query: buildTrendsQuery() })
            const button = await waitForBreakdownButton()
            expect(button).toHaveAttribute('aria-disabled', 'false')
        })
    })

    describe('at the trends 3-breakdown cap', () => {
        const queryAtCap = buildTrendsQuery({
            breakdownFilter: {
                breakdowns: [
                    { property: '$browser', type: 'event' },
                    { property: '$os', type: 'event' },
                    { property: '$device_type', type: 'event' },
                ],
            },
        })

        it('keeps the + Breakdown button rendered but disabled', async () => {
            renderInsightPage({ query: queryAtCap })
            const button = await waitForBreakdownButton()
            expect(button).toBeInTheDocument()
            expect(button).toHaveAttribute('aria-disabled', 'true')
        })

        it('surfaces the trends cap explanation on hover', async () => {
            renderInsightPage({ query: queryAtCap })
            const button = await waitForBreakdownButton()
            await userEvent.hover(button)
            await waitFor(() => {
                expect(screen.getByText(/up to 3 properties/i)).toBeInTheDocument()
            })
        })

        it('embeds the docs link inline in the tooltip', async () => {
            renderInsightPage({ query: queryAtCap })
            const button = await waitForBreakdownButton()
            await userEvent.hover(button)
            await waitFor(() => {
                const docsLink = screen.getByText(/read the docs/i).closest('a')
                expect(docsLink).not.toBeNull()
                expect(docsLink).toHaveAttribute('href', 'https://posthog.com/docs/product-analytics/trends/breakdowns')
            })
        })

        it('offers the SQL editor escape hatch when the insight is SQL-convertible', async () => {
            renderInsightPage({
                query: queryAtCap,
                mocks: {
                    mockResponses: [
                        {
                            match: (query) => query.kind === NodeKind.TrendsQuery,
                            response: { results: [], hogql: 'SELECT count() FROM events' } as any,
                        },
                    ],
                },
            })
            const button = await waitForBreakdownButton()
            await userEvent.hover(button)
            await waitFor(() => {
                const sqlLink = screen.getByTestId('breakdown-limit-edit-sql')
                expect(sqlLink).toBeInTheDocument()
                expect(sqlLink.getAttribute('href')).toMatch(/\/sql/)
            })
        })
    })

    describe('on a data warehouse series', () => {
        const warehouseQuery: TrendsQuery = buildTrendsQuery({
            series: [
                {
                    kind: NodeKind.DataWarehouseNode,
                    id: 'ad_stats',
                    name: 'ad_stats',
                    table_name: 'ad_stats',
                    id_field: 'id',
                    timestamp_field: 'reported_at',
                    distinct_id_field: 'account_id',
                },
            ],
        })

        const warehouseSchema = {
            tables: {
                ad_stats: {
                    name: 'ad_stats',
                    type: 'data_warehouse',
                    id: 'ad_stats',
                    fields: {
                        campaign_id: { name: 'campaign_id', hogql_value: 'campaign_id', type: 'string' },
                        campaign: {
                            name: 'campaign',
                            hogql_value: 'campaign',
                            type: 'lazy_table',
                            table: 'campaigns',
                        },
                    },
                },
                campaigns: {
                    name: 'campaigns',
                    type: 'data_warehouse',
                    id: 'campaigns',
                    fields: {
                        campaign_name: { name: 'campaign_name', hogql_value: 'campaign_name', type: 'string' },
                    },
                },
            },
        }

        it('offers a joined table column and the SQL expression escape hatch', async () => {
            renderInsightPage({
                query: warehouseQuery,
                mocks: {
                    additionalMockResponses: [
                        {
                            match: (query) => query.kind === NodeKind.DatabaseSchemaQuery,
                            response: warehouseSchema as any,
                        },
                    ],
                },
            })
            await userEvent.click(await waitForBreakdownButton())

            await waitFor(() => {
                expect(screen.getAllByText('campaign.campaign_name').length).toBeGreaterThan(0)
            })
            expect(screen.getByText(/SQL expression/i)).toBeInTheDocument()
        })
    })

    describe('at the funnel cohort cap', () => {
        it('surfaces the funnel cohort explanation and the cohort-anchored docs link', async () => {
            renderInsightPage({
                query: {
                    kind: NodeKind.FunnelsQuery,
                    series: [
                        { kind: NodeKind.EventsNode, event: '$pageview', name: '$pageview' },
                        { kind: NodeKind.EventsNode, event: '$pageview', name: '$pageview' },
                    ],
                    breakdownFilter: {
                        breakdown_type: 'cohort',
                        breakdown: [1],
                    },
                } as any,
            })
            const button = await waitForBreakdownButton()
            expect(button).toHaveAttribute('aria-disabled', 'true')
            await userEvent.hover(button)
            await waitFor(() => {
                expect(screen.getByText(/single cohort breakdown/i)).toBeInTheDocument()
                const docsLink = screen.getByText(/read the docs/i).closest('a')
                expect(docsLink).not.toBeNull()
                expect(docsLink).toHaveAttribute(
                    'href',
                    'https://posthog.com/docs/product-analytics/trends/breakdowns#cohorts-and-breakdowns'
                )
            })
        })
    })
})

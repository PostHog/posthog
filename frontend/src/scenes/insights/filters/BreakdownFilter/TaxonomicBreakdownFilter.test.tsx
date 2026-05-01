import '@testing-library/jest-dom'

import { cleanup, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { NodeKind } from '~/queries/schema/schema-general'
import { buildTrendsQuery, renderInsightPage } from '~/test/insight-testing'

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
                const docsLink = screen.getByRole('link', { name: /read the docs/i })
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
                const docsLink = screen.getByRole('link', { name: /read the docs/i })
                expect(docsLink).toHaveAttribute(
                    'href',
                    'https://posthog.com/docs/product-analytics/trends/breakdowns#cohorts-and-breakdowns'
                )
            })
        })
    })
})

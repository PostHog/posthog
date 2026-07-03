import { cleanup, render, waitFor } from '@testing-library/react'

import { DataVisualizationNode, HogQLQueryResponse, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { ChartDisplayType } from '~/types'

import { DataTableVisualization } from './DataVisualization'

type LemonTableMockProps = {
    embedded?: boolean
    allowContentScroll?: boolean
}

let mockLatestLemonTableProps: LemonTableMockProps | null = null
const mockLemonTable = jest.fn((props: LemonTableMockProps): null => {
    mockLatestLemonTableProps = props
    return null
})

jest.mock('@posthog/lemon-ui', () => ({
    ...jest.requireActual('@posthog/lemon-ui'),
    LemonTable: (props: Record<string, unknown>): null => {
        mockLemonTable(props)
        return null
    },
}))

describe('DataTableVisualization', () => {
    const query: DataVisualizationNode = {
        kind: NodeKind.DataVisualizationNode,
        source: {
            kind: NodeKind.HogQLQuery,
            query: 'select number from numbers(2)',
        },
        display: ChartDisplayType.ActionsTable,
    }

    const hogqlQueryWithDateRange: DataVisualizationNode = {
        kind: NodeKind.DataVisualizationNode,
        source: {
            kind: NodeKind.HogQLQuery,
            query: 'SELECT count() FROM events WHERE timestamp >= {filters.dateRange.from}',
            filters: {
                dateRange: {
                    date_from: '-7d',
                    date_to: null,
                },
            },
        },
        display: ChartDisplayType.ActionsTable,
    }

    const cachedResults: HogQLQueryResponse<number[][]> = {
        results: [[1], [2]],
        columns: ['number'],
        types: [['number', 'Int64']],
    }

    beforeEach(() => {
        initKeaTests()
        mockLatestLemonTableProps = null
        mockLemonTable.mockClear()
    })

    afterEach(() => {
        cleanup()
    })

    it('shows the date filter in read-only view mode when the HogQL query uses filter placeholders', async () => {
        const { container } = render(
            <DataTableVisualization
                uniqueKey="data-visualization-read-only-date-range"
                query={hogqlQueryWithDateRange}
                setQuery={jest.fn()}
                cachedResults={cachedResults}
                readOnly
            />
        )

        await waitFor(() => {
            expect(container.querySelector('[data-attr="date-filter"]')).toBeTruthy()
        })
    })

    it('hides the date filter in read-only view mode when the HogQL query has no filter placeholders', async () => {
        const { container } = render(
            <DataTableVisualization
                uniqueKey="data-visualization-read-only-no-date-range"
                query={query}
                setQuery={jest.fn()}
                cachedResults={cachedResults}
                readOnly
            />
        )

        await waitFor(() => {
            if (!mockLatestLemonTableProps) {
                throw new Error('Expected LemonTable to render')
            }
        })

        expect(container.querySelector('[data-attr="date-filter"]')).toBeNull()
    })

    test.each([
        { embedded: true, expectedAllowContentScroll: true },
        { embedded: false, expectedAllowContentScroll: false },
    ])(
        'sets table scroll mode to $expectedAllowContentScroll when embedded is $embedded',
        async ({ embedded, expectedAllowContentScroll }) => {
            render(
                <DataTableVisualization
                    uniqueKey={`data-visualization-scroll-${embedded}`}
                    query={query}
                    setQuery={jest.fn()}
                    cachedResults={cachedResults}
                    readOnly
                    embedded={embedded}
                />
            )

            await waitFor(() => {
                if (!mockLatestLemonTableProps) {
                    throw new Error('Expected LemonTable to render')
                }
            })

            if (!mockLatestLemonTableProps) {
                throw new Error('Expected LemonTable props to be recorded')
            }
            expect(mockLatestLemonTableProps.embedded).toBe(embedded)
            expect(mockLatestLemonTableProps.allowContentScroll).toBe(expectedAllowContentScroll)
        }
    )
})

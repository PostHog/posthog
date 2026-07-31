import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'

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

jest.mock('./Components/Charts/SqlChart', () => ({
    SqlChart: (): null => null,
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

    test.each([
        { embedded: false, description: 'full insight view' },
        { embedded: true, description: 'dashboard tile' },
    ])('shows a row limit notice on a chart when the result was truncated ($description)', async ({ embedded }) => {
        const chartQuery: DataVisualizationNode = { ...query, display: ChartDisplayType.ActionsLineGraph }
        const truncatedResults: HogQLQueryResponse<number[][]> = { ...cachedResults, hasMore: true, limit: 100 }

        render(
            <DataTableVisualization
                uniqueKey={`data-visualization-row-limit-${embedded}`}
                query={chartQuery}
                setQuery={jest.fn()}
                cachedResults={truncatedResults}
                readOnly
                embedded={embedded}
            />
        )

        await waitFor(() => expect(screen.getByText(/Showing first 100 rows/)).toBeInTheDocument())
    })

    it('does not show a row limit notice on a chart when the result was not truncated', async () => {
        const chartQuery: DataVisualizationNode = { ...query, display: ChartDisplayType.ActionsLineGraph }

        render(
            <DataTableVisualization
                uniqueKey="data-visualization-row-limit-not-truncated"
                query={chartQuery}
                setQuery={jest.fn()}
                cachedResults={cachedResults}
                readOnly
            />
        )

        await waitFor(() => expect(screen.queryByText(/Showing first/)).not.toBeInTheDocument())
    })
})

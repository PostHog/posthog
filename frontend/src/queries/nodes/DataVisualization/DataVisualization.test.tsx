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

// The chart components rely on canvas, which jsdom lacks; the truncation banner is what we assert.
jest.mock('./Components/Charts/SqlChart', () => ({ SqlChart: (): null => null }))

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

    const truncatedResults: HogQLQueryResponse<number[][]> = {
        ...cachedResults,
        hasMore: true,
        limit: 100,
    }

    test('warns that a truncated chart result was limited', async () => {
        render(
            <DataTableVisualization
                uniqueKey="data-visualization-truncated-chart"
                query={{ ...query, display: ChartDisplayType.ActionsLineGraph }}
                setQuery={jest.fn()}
                cachedResults={truncatedResults}
                readOnly
            />
        )

        await waitFor(() => {
            expect(screen.queryByText('Results limited to 100 rows – add a LIMIT clause to override')).not.toBeNull()
        })
    })

    test('does not add the chart truncation banner for a truncated table result', async () => {
        render(
            <DataTableVisualization
                uniqueKey="data-visualization-truncated-table"
                query={query}
                setQuery={jest.fn()}
                cachedResults={truncatedResults}
                readOnly
            />
        )

        await waitFor(() => {
            if (!mockLatestLemonTableProps) {
                throw new Error('Expected LemonTable to render')
            }
        })

        expect(screen.queryByText('Results limited to 100 rows – add a LIMIT clause to override')).toBeNull()
    })
})

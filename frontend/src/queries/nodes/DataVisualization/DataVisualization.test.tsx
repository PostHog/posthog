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
        { name: 'the backend cut the result', hasMore: true, limit: 100, expectNotice: true },
        { name: 'the result fits under the default limit', hasMore: false, limit: 100, expectNotice: false },
        { name: 'the query declares its own limit', hasMore: undefined, limit: undefined, expectNotice: false },
    ])('embedded tile tells the reader when $name', async ({ hasMore, limit, expectNotice }) => {
        render(
            <DataTableVisualization
                uniqueKey={`data-visualization-limit-${String(hasMore)}-${String(limit)}`}
                query={query}
                setQuery={jest.fn()}
                cachedResults={{ ...cachedResults, hasMore, limit }}
                readOnly
                embedded
            />
        )

        await waitFor(() => {
            if (!mockLatestLemonTableProps) {
                throw new Error('Expected LemonTable to render')
            }
        })

        expect(screen.queryByText(/Try adding a LIMIT clause to adjust/)).toEqual(
            expectNotice ? expect.anything() : null
        )
    })
})

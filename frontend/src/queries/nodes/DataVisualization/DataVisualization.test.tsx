import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'

import { VisualizationNode, HogQLQueryResponse, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { ChartDisplayType } from '~/types'

import { DataTableVisualization } from './DataVisualization'

type LemonTableMockProps = {
    embedded?: boolean
    allowContentScroll?: boolean
    dataSource?: unknown[]
    columns?: { render: (value: unknown, record: unknown, index: number, rowCount: number) => JSX.Element }[]
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
    const query: VisualizationNode = {
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
        { showAbsoluteTime: true, expectedText: /January 15, 2020/ },
        { showAbsoluteTime: false, expectedText: /ago$/ },
    ])(
        'renders datetime cells matching $expectedText when showAbsoluteTime is $showAbsoluteTime',
        async ({ showAbsoluteTime, expectedText }) => {
            render(
                <DataTableVisualization
                    uniqueKey={`data-visualization-absolute-time-${showAbsoluteTime}`}
                    query={{
                        ...query,
                        source: { kind: NodeKind.HogQLQuery, query: 'select created_at from events' },
                        tableSettings: { showAbsoluteTime },
                    }}
                    setQuery={jest.fn()}
                    cachedResults={{
                        results: [['2020-01-15T12:00:00Z']],
                        columns: ['created_at'],
                        types: [['created_at', "DateTime64(6, 'UTC')"]],
                    }}
                    readOnly
                />
            )

            await waitFor(() => {
                if (!mockLatestLemonTableProps?.dataSource?.length) {
                    throw new Error('Expected LemonTable to render with rows')
                }
            })

            const { columns, dataSource } = mockLatestLemonTableProps as Required<LemonTableMockProps>
            render(columns[0].render(undefined, dataSource[0], 0, 1))

            expect(screen.getByText(expectedText)).toBeInTheDocument()
        }
    )
})

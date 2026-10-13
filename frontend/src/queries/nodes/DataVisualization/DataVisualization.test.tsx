import '@testing-library/jest-dom'

import { act, cleanup, render, screen, waitFor } from '@testing-library/react'

import { VisualizationNode, HogQLQueryResponse, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { ChartDisplayType } from '~/types'

import { DataTableVisualization } from './DataVisualization'

type LemonTableMockProps = {
    embedded?: boolean
    allowContentScroll?: boolean
    dataSource?: unknown[]
    columns?: {
        render: (value: unknown, record: unknown, index: number, rowCount: number) => JSX.Element
        more?: JSX.Element
    }[]
    sorting?: { columnKey: string; order: number } | null
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
        localStorage.clear()
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

    // Read-only with a setQuery that never feeds back, like a dashboard tile for a viewer who can't edit.
    const renderSingleColumnTable = async (
        type: string,
        savedShowAbsoluteTime?: boolean
    ): Promise<Required<LemonTableMockProps> & { refreshQuery: () => void }> => {
        const tableQuery = {
            ...query,
            source: { kind: NodeKind.HogQLQuery, query: 'select created_at from events' },
            tableSettings: { showAbsoluteTime: savedShowAbsoluteTime },
        } as VisualizationNode
        const tableElement = (tableQuery: VisualizationNode): JSX.Element => (
            <DataTableVisualization
                uniqueKey={`data-visualization-column-menu-${type}-${savedShowAbsoluteTime}`}
                query={tableQuery}
                setQuery={jest.fn()}
                cachedResults={{
                    results: [['2020-01-15T12:00:00Z'], ['2020-03-01T12:00:00Z']],
                    columns: ['created_at'],
                    types: [['created_at', type]],
                }}
                readOnly
            />
        )
        const { rerender } = render(tableElement(tableQuery))
        await waitFor(() => {
            if (!mockLatestLemonTableProps?.dataSource?.length) {
                throw new Error('Expected LemonTable to render with rows')
            }
        })
        return {
            ...(mockLatestLemonTableProps as Required<LemonTableMockProps>),
            refreshQuery: () => rerender(tableElement({ ...tableQuery })),
        }
    }

    test.each([
        { type: "DateTime64(6, 'UTC')", offersTimeToggle: true },
        { type: 'Date', offersTimeToggle: false },
        { type: 'String', offersTimeToggle: false },
    ])(
        'the column menu for a $type column offers the time toggle: $offersTimeToggle',
        async ({ type, offersTimeToggle }) => {
            const { columns } = await renderSingleColumnTable(type)
            render(columns[0].more as JSX.Element)

            expect(screen.getByText('Sort ascending')).toBeInTheDocument()
            expect(screen.queryByText('Show absolute time') !== null).toBe(offersTimeToggle)
        }
    )

    test.each([
        { savedShowAbsoluteTime: undefined, menuItem: 'Show absolute time', expectedText: /January 15, 2020/ },
        { savedShowAbsoluteTime: false, menuItem: 'Show absolute time', expectedText: /January 15, 2020/ },
        { savedShowAbsoluteTime: true, menuItem: 'Show relative time', expectedText: /ago$/ },
    ])(
        'a viewer choosing "$menuItem" over a saved setting of $savedShowAbsoluteTime keeps it after a refresh',
        async ({ savedShowAbsoluteTime, menuItem, expectedText }) => {
            const { columns, refreshQuery } = await renderSingleColumnTable(
                "DateTime64(6, 'UTC')",
                savedShowAbsoluteTime
            )
            render(columns[0].more as JSX.Element)
            act(() => screen.getByText(menuItem).click())
            act(() => refreshQuery())

            const latest = mockLatestLemonTableProps as Required<LemonTableMockProps>
            render(latest.columns[0].render(undefined, latest.dataSource[0], 0, 2))
            expect(screen.getByText(expectedText)).toBeInTheDocument()
        }
    )

    test.each([
        { item: 'Sort descending', expectedSorting: { columnKey: 'created_at', order: -1 } },
        { item: 'Reset sorting', expectedSorting: null },
    ])('the column menu item "$item" sets the table sorting', async ({ item, expectedSorting }) => {
        const { columns } = await renderSingleColumnTable("DateTime64(6, 'UTC')")
        render(columns[0].more as JSX.Element)
        screen.getByText('Sort ascending').click()
        screen.getByText(item).click()

        await waitFor(() => expect(mockLatestLemonTableProps?.sorting).toEqual(expectedSorting))
    })
})

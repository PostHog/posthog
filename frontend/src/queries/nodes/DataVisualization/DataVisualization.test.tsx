import { cleanup, fireEvent, render, waitFor } from '@testing-library/react'

import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { DataVisualizationNode, HogQLQueryResponse, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { ChartDisplayType } from '~/types'

import { DataTableVisualization } from './DataVisualization'

type LemonTableMockProps = {
    embedded?: boolean
    allowContentScroll?: boolean
    columns?: { key?: string; render: (...args: any[]) => React.ReactNode }[]
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

jest.mock('lib/utils/copyToClipboard', () => ({
    copyToClipboard: jest.fn(),
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

    it('copies a plain-text cell value to the clipboard on click', async () => {
        const shaQuery: DataVisualizationNode = {
            kind: NodeKind.DataVisualizationNode,
            source: {
                kind: NodeKind.HogQLQuery,
                query: 'select sha from commits',
            },
            display: ChartDisplayType.ActionsTable,
        }
        const shaResults: HogQLQueryResponse<string[][]> = {
            results: [['a1b2c3d']],
            columns: ['sha'],
            types: [['sha', 'String']],
        }

        render(
            <DataTableVisualization
                uniqueKey="data-visualization-copy"
                query={shaQuery}
                setQuery={jest.fn()}
                cachedResults={shaResults}
                readOnly
            />
        )

        await waitFor(() => {
            if (!mockLatestLemonTableProps?.columns) {
                throw new Error('Expected LemonTable to render with columns')
            }
        })

        const shaColumn = mockLatestLemonTableProps!.columns!.find((column) => column.key === 'sha')
        if (!shaColumn) {
            throw new Error('Expected a "sha" column')
        }

        const cellData = [{ value: 'a1b2c3d', formattedValue: 'a1b2c3d', type: 'STRING' }]
        const { getByText } = render(shaColumn.render(undefined, cellData, 0, 1))

        fireEvent.click(getByText('a1b2c3d'))

        expect(copyToClipboard).toHaveBeenCalledWith('a1b2c3d', 'cell value')
    })
})

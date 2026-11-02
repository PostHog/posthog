import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'

import type { RadialSlicePayload } from '@posthog/quill-charts'

import { BIField } from '~/queries/schema/schema-business-intelligence'
import { VisualizationNode, HogQLQueryResponse, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { renderDataVisualization } from '~/test/insight-testing'
import { ChartDisplayType } from '~/types'

import { buildBIQuery, DEFAULT_BI_CONFIG } from 'products/business_intelligence/frontend/biEditorTypes'

import type { SqlChartProps } from './Components/Charts/SqlChart'
import { buildPieSeries, buildPieSlices } from './Components/Charts/sqlPieGraphAdapter'
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

jest.mock('./Components/Charts/PartOfWholeChart', () => ({
    PartOfWholeChart: ({ xData, yData, onSliceClick }: SqlChartProps): JSX.Element => (
        <button
            onClick={() =>
                onSliceClick?.({ series: buildPieSeries(buildPieSlices(xData, yData))[0] } as RadialSlicePayload)
            }
        >
            First slice
        </button>
    ),
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

    it.each([
        { breakdown: false, alias: false },
        { breakdown: true, alias: false },
        { breakdown: false, alias: true },
        { breakdown: true, alias: true },
    ])('keeps the raw pie selection with breakdown=$breakdown and alias=$alias', async ({ breakdown, alias }) => {
        const field = (name: string): BIField => ({
            id: name,
            name,
            expression: name,
            type: 'string',
            source: { table: 'events' },
        })
        const region = field('region')
        const regionColumn = 'region'
        const config = {
            ...DEFAULT_BI_CONFIG,
            source: region.source,
            chartType: ChartDisplayType.ActionsPie,
            rows: [breakdown ? field('segment') : region],
            columns: breakdown ? [region] : [],
            memberAliases: alias ? [{ field: region, aliases: [{ value: 'west', label: 'West coast' }] }] : [],
        }
        renderDataVisualization({
            embedded: true,
            context: { dashboardResultMenu: true },
            query: {
                ...buildBIQuery(config)!.node,
                kind: NodeKind.BIVisualizationNode,
                config,
                chartSettings: {
                    xAxis: { column: breakdown ? 'segment' : regionColumn },
                    yAxis: [{ column: 'count' }],
                    ...(breakdown ? { seriesBreakdownColumn: regionColumn } : {}),
                },
            },
            response: breakdown
                ? {
                      columns: ['segment', regionColumn, 'count'],
                      types: [
                          ['segment', 'String'],
                          [regionColumn, 'String'],
                          ['count', 'Int64'],
                      ],
                      results: [['first', 'west', 2]],
                  }
                : {
                      columns: [regionColumn, 'count'],
                      types: [
                          [regionColumn, 'String'],
                          ['count', 'Int64'],
                      ],
                      results: [['west', 2]],
                  },
        })
        fireEvent.contextMenu(await screen.findByText('First slice'))
        const menu = await screen.findByRole('menu')
        const link = within(menu).getByText('Open in SQL editor').closest('a')!
        const openedQuery = JSON.parse(new URL(link.href).searchParams.get('open_query')!)
        expect(openedQuery.source.query).toContain("region = 'west'")
        expect(openedQuery.source.query).not.toContain("region = 'West coast'")
        fireEvent.click(screen.getByText('First slice'))
        expect(screen.queryByRole('menu')).toBeNull()
        await screen.findByText('Explore this result')
    })

    it.each([false, true])('opens and closes settings in the correct panel (hosted: %s)', async (hosted) => {
        function Visualization(): JSX.Element {
            const [container, setContainer] = useState<HTMLDivElement | null>(null)
            const [isOpen, setIsOpen] = useState(false)
            return (
                <>
                    <div ref={setContainer} data-attr="host-settings" />
                    <DataTableVisualization
                        uniqueKey={`settings-${hosted}`}
                        query={query}
                        setQuery={jest.fn()}
                        cachedResults={cachedResults}
                        editMode
                        context={
                            hosted
                                ? {
                                      visualizationSettingsPanel: {
                                          container,
                                          isOpen,
                                          onToggle: () => setIsOpen(!isOpen),
                                      },
                                  }
                                : undefined
                        }
                    />
                </>
            )
        }
        const { container } = render(<Visualization />)
        expect(screen.queryByText('Conditional formatting')).toBeNull()
        await userEvent.click(screen.getByLabelText('Visualization settings'))
        const settings = await screen.findByText('Conditional formatting')
        const host = screen.getByTestId('host-settings')
        expect(host.contains(settings)).toBe(hosted)
        expect(container.querySelector('.DataVisualization')!.contains(settings)).toBe(!hosted)
        await userEvent.click(settings)
        expect(within(hosted ? host : container).getByText('Add rule')).toBeTruthy()
        await userEvent.click(screen.getByLabelText('Visualization settings'))
        expect(screen.queryByText('Conditional formatting')).toBeNull()
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

import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BindLogic, Provider } from 'kea'

import { ChartFilter } from 'lib/components/ChartFilter/ChartFilter'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { openPersonsModal } from 'scenes/trends/persons-modal/PersonsModal'

import { useMocks } from '~/mocks/jest'
import { NodeKind, TrendsQueryResponse } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { buildTrendsQuery, MockResponse, renderInsightPage } from '~/test/insight-testing'
import { ChartDisplayType } from '~/types'
import { InsightShortId } from '~/types'

import { ChangeChartView } from './ChangeChart'
import { ChangeChartDisplayRow } from './changeChartLogic'

jest.mock('scenes/trends/persons-modal/PersonsModal')

const changeChartResponse = (): TrendsQueryResponse =>
    ({
        results: [
            {
                action: { id: '$pageview', type: 'events', name: '$pageview', order: 0 },
                label: '$pageview',
                count: 100,
                aggregated_value: 100,
                data: [],
                days: [],
                labels: [],
                breakdown_value: 'New York',
                compare: true,
                compare_label: 'current',
            },
            {
                action: { id: '$pageview', type: 'events', name: '$pageview', order: 0 },
                label: '$pageview',
                count: 90,
                aggregated_value: 90,
                data: [],
                days: [],
                labels: [],
                breakdown_value: 'New York',
                compare: true,
                compare_label: 'previous',
            },
            {
                action: { id: '$pageview', type: 'events', name: '$pageview', order: 0 },
                label: '$pageview',
                count: 45,
                aggregated_value: 45,
                data: [],
                days: [],
                labels: [],
                breakdown_value: 'Los Angeles',
                compare: true,
                compare_label: 'current',
            },
            {
                action: { id: '$pageview', type: 'events', name: '$pageview', order: 0 },
                label: '$pageview',
                count: 60,
                aggregated_value: 60,
                data: [],
                days: [],
                labels: [],
                breakdown_value: 'Los Angeles',
                compare: true,
                compare_label: 'previous',
            },
        ],
    }) as TrendsQueryResponse

const compareMock: MockResponse = {
    match: (query) => query.kind === NodeKind.TrendsQuery,
    response: changeChartResponse,
}

const Insight123 = '123' as InsightShortId
const insightProps = { dashboardItemId: Insight123 }

function renderChartFilter(query = buildTrendsQuery()): ReturnType<typeof insightVizDataLogic.build> {
    initKeaTests()
    featureFlagLogic().mount()

    insightLogic(insightProps).mount()
    insightDataLogic(insightProps).mount()
    const vizDataLogic = insightVizDataLogic(insightProps)
    vizDataLogic.mount()
    vizDataLogic.actions.updateQuerySource(query)

    render(
        <Provider>
            <BindLogic logic={insightLogic} props={insightProps}>
                <ChartFilter />
            </BindLogic>
        </Provider>
    )

    return vizDataLogic
}

describe('ChangeChart', () => {
    afterEach(() => {
        cleanup()
    })

    describe('ChangeChartView', () => {
        const rows: ChangeChartDisplayRow[] = [
            {
                key: 'new-york',
                label: 'New York',
                metricLabel: '$pageview',
                currentValueLabel: '100',
                previousValueLabel: '90',
                changeLabel: '+35%',
                rawRow: {
                    breakdownValue: 'New York',
                    current: null,
                    previous: null,
                    currentValue: 100,
                    previousValue: 90,
                    absoluteChange: 10,
                    percentChange: 35,
                    direction: 'up',
                    sortValue: 35,
                },
            },
            {
                key: 'los-angeles',
                label: 'Los Angeles',
                metricLabel: '$pageview',
                currentValueLabel: '90',
                previousValueLabel: '100',
                changeLabel: '-10.5%',
                rawRow: {
                    breakdownValue: 'Los Angeles',
                    current: null,
                    previous: null,
                    currentValue: 90,
                    previousValue: 100,
                    absoluteChange: -10,
                    percentChange: -10.5,
                    direction: 'down',
                    sortValue: -10.5,
                },
            },
            {
                key: 'austin',
                label: 'Austin',
                metricLabel: '$pageview',
                currentValueLabel: '5',
                previousValueLabel: 'No data',
                changeLabel: 'No previous data',
                rawRow: {
                    breakdownValue: 'Austin',
                    current: null,
                    previous: null,
                    currentValue: 5,
                    previousValue: null,
                    absoluteChange: null,
                    percentChange: null,
                    direction: 'unavailable',
                    sortValue: Number.NEGATIVE_INFINITY,
                },
            },
        ]

        it('renders diverging rows, secondary values, and a previous-versus-current tooltip', async () => {
            const onRowClick = jest.fn()
            const { container } = render(
                <ChangeChartView
                    rows={rows}
                    axisLabels={['-40%', '-20%', '0%', '20%', '40%']}
                    domain={40}
                    previousPeriodLabel="Previous period"
                    currentPeriodLabel="Current period"
                    displayMode="relative"
                    hoveredTooltip={null}
                    showCurrentValue={true}
                    onHover={jest.fn()}
                    onLeave={jest.fn()}
                    onRowClick={onRowClick}
                />
            )

            expect(screen.getByText('Current')).toBeInTheDocument()
            expect(screen.getByText('Breakdown')).toBeInTheDocument()
            expect(screen.getByText('New York')).toBeInTheDocument()
            expect(screen.getByText('Los Angeles')).toBeInTheDocument()
            expect(screen.getByText('Austin')).toBeInTheDocument()
            expect(screen.getByText('+35%')).toBeInTheDocument()
            expect(screen.getByText('-10.5%')).toBeInTheDocument()

            expect(container.querySelectorAll('.bg-success-highlight')).toHaveLength(1)
            expect(container.querySelectorAll('.bg-danger-highlight')).toHaveLength(1)

            await userEvent.hover(screen.getByText('New York'))
            await userEvent.click(screen.getByText('Los Angeles'))
            expect(onRowClick).toHaveBeenCalledWith(rows[1])
        })

        it('can hide the current value column', () => {
            render(
                <ChangeChartView
                    rows={rows}
                    axisLabels={['-40%', '-20%', '0%', '20%', '40%']}
                    domain={40}
                    previousPeriodLabel="Previous period"
                    currentPeriodLabel="Current period"
                    displayMode="relative"
                    hoveredTooltip={null}
                    showCurrentValue={false}
                    onHover={jest.fn()}
                    onLeave={jest.fn()}
                />
            )

            expect(screen.queryByText('Current')).not.toBeInTheDocument()
            expect(screen.getByText('Breakdown')).toBeInTheDocument()
        })

        it('uses the aggregation formatter for absolute-mode axis labels', () => {
            render(
                <ChangeChartView
                    rows={rows}
                    axisLabels={['formatted:-20', 'formatted:-10', 'formatted:0', 'formatted:10', 'formatted:20']}
                    domain={20}
                    previousPeriodLabel="Previous period"
                    currentPeriodLabel="Current period"
                    displayMode="absolute"
                    hoveredTooltip={null}
                    showCurrentValue={true}
                    onHover={jest.fn()}
                    onLeave={jest.fn()}
                />
            )

            expect(screen.getByText('formatted:-20')).toBeInTheDocument()
            expect(screen.getByText('formatted:-10')).toBeInTheDocument()
            expect(screen.getByText('formatted:0')).toBeInTheDocument()
            expect(screen.getByText('formatted:10')).toBeInTheDocument()
            expect(screen.getByText('formatted:20')).toBeInTheDocument()
        })

        it('renders the hover tooltip through a portal', () => {
            const { container } = render(
                <ChangeChartView
                    rows={rows}
                    axisLabels={['-40%', '-20%', '0%', '20%', '40%']}
                    domain={40}
                    previousPeriodLabel="Previous period"
                    currentPeriodLabel="Current period"
                    displayMode="relative"
                    hoveredTooltip={{ row: rows[0], x: 100, y: 120 }}
                    showCurrentValue={true}
                    onHover={jest.fn()}
                    onLeave={jest.fn()}
                />
            )

            expect(screen.getByText('Previous period')).toBeInTheDocument()
            expect(screen.getByText('Current period')).toBeInTheDocument()
            expect(container).not.toContainElement(screen.getByText('Previous period'))
        })
    })

    describe('insight integration', () => {
        it('forces previous-period compare state, hides the compare picker, and restores the prior compare selection when leaving', async () => {
            useMocks({
                get: {
                    '/api/environments/:team_id/insights/trend': [],
                    '/api/environments/:team_id/insights/': { results: [{}] },
                },
            })

            const vizDataLogic = renderChartFilter(
                buildTrendsQuery({
                    dateRange: { date_from: '-24h', explicitDate: false },
                    breakdownFilter: { breakdown: '$browser' },
                    compareFilter: { compare: true, compare_to: '-30d' },
                })
            )

            await userEvent.click(screen.getByTestId('chart-filter'))
            await userEvent.click(screen.getByRole('menuitem', { name: /^Change chart Change versus/ }))

            await waitFor(() => {
                expect(vizDataLogic.values.querySource.trendsFilter?.display).toBe(ChartDisplayType.ChangeChart)
                expect(vizDataLogic.values.querySource.compareFilter).toEqual({ compare: true })
                expect(vizDataLogic.values.querySource.dateRange?.explicitDate).toBe(true)
            })

            await userEvent.click(screen.getByTestId('chart-filter'))
            await userEvent.click(screen.getByRole('menuitem', { name: /^Line chart Trends over time/ }))

            await waitFor(() => {
                expect(vizDataLogic.values.querySource.trendsFilter?.display).toBe(ChartDisplayType.ActionsLineGraph)
                expect(vizDataLogic.values.querySource.compareFilter).toEqual({
                    compare: true,
                    compare_to: '-30d',
                })
                expect(vizDataLogic.values.querySource.dateRange?.explicitDate).toBe(false)
            })
        })

        it('renders the change chart in Trends and drills down using the current-period breakdown', async () => {
            const { container } = renderInsightPage({
                query: buildTrendsQuery({
                    breakdownFilter: { breakdown: '$geoip_city_name' },
                    trendsFilter: { display: ChartDisplayType.ChangeChart },
                    compareFilter: { compare: true },
                }),
                showFilters: false,
                mocks: { mockResponses: [compareMock] },
            })

            expect(await screen.findByText('New York')).toBeInTheDocument()
            expect(await screen.findByText('+11.1%')).toBeInTheDocument()
            expect(container.querySelector('[data-attr="change-chart"]')).toBeInTheDocument()

            await userEvent.click(screen.getAllByText('New York')[0])

            expect(openPersonsModal).toHaveBeenCalledWith(
                expect.objectContaining({
                    title: 'New York',
                    query: expect.objectContaining({
                        kind: 'InsightActorsQuery',
                        breakdown: 'New York',
                        compare: 'current',
                    }),
                })
            )
        })
    })
})

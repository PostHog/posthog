import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BindLogic, Provider } from 'kea'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { useMocks } from '~/mocks/jest'
import {
    InsightQueryNode,
    LifecycleQuery,
    NodeKind,
    RetentionQuery,
    StickinessQuery,
    TrendsQuery,
} from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { BaseMathType, ChartDisplayType, InsightShortId } from '~/types'

import { InsightDisplayConfig } from './InsightDisplayConfig'

const Insight123 = '123' as InsightShortId
const insightProps = { dashboardItemId: Insight123 }

const pageviewSeries = [
    {
        kind: NodeKind.EventsNode,
        name: '$pageview',
        event: '$pageview',
        math: BaseMathType.TotalCount,
    },
] as const

function makeTrendsQuery(
    display?: ChartDisplayType,
    trendsFilter: NonNullable<TrendsQuery['trendsFilter']> = {}
): TrendsQuery {
    return {
        kind: NodeKind.TrendsQuery,
        series: [...pageviewSeries],
        trendsFilter: {
            display,
            ...trendsFilter,
        },
    }
}

function makeRetentionQuery(): RetentionQuery {
    return { kind: NodeKind.RetentionQuery, retentionFilter: {} }
}

function makeStickinessQuery(): StickinessQuery {
    return { kind: NodeKind.StickinessQuery, series: [...pageviewSeries] }
}

function makeLifecycleQuery(): LifecycleQuery {
    return { kind: NodeKind.LifecycleQuery, series: [...pageviewSeries] }
}

function getSectionTitles(): string[] {
    return screen.getAllByRole('heading', { level: 5 }).map((h) => h.textContent?.replace(/\s+/g, ' ').trim() ?? '')
}

async function openOptionsMenu(): Promise<void> {
    const optionsButtons = screen.getAllByRole('button', { name: /Options/ })
    await userEvent.click(optionsButtons[0])
}

function getDisplaySectionItems(): string[] {
    const displaySection = screen.getByTestId('options-display-section').closest('section')!
    const listItems = within(displaySection).getAllByRole('listitem')
    return listItems.map((li) => li.textContent?.trim() || '')
}

describe('InsightDisplayConfig', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/insights/trend': [],
                '/api/environments/:team_id/insights/': { results: [{}] },
            },
        })
        initKeaTests()
        featureFlagLogic().mount()
    })

    afterEach(() => {
        cleanup()
    })

    function setupAndRender(query: InsightQueryNode): void {
        insightLogic(insightProps).mount()
        insightDataLogic(insightProps).mount()
        const vizDataLogic = insightVizDataLogic(insightProps)
        vizDataLogic.mount()
        vizDataLogic.actions.updateQuerySource(query)

        render(
            <Provider>
                <BindLogic logic={insightLogic} props={insightProps}>
                    <InsightDisplayConfig />
                </BindLogic>
            </Provider>
        )
    }

    describe('Options menu sections per insight/chart type', () => {
        const cases: [string, InsightQueryNode, string[]][] = [
            [
                'trends line graph',
                makeTrendsQuery(ChartDisplayType.ActionsLineGraph),
                [
                    'Display',
                    'Color customization by',
                    'Y-axis unit',
                    'Y-axis scale',
                    'Statistical analysis',
                    'Axis labels',
                ],
            ],
            [
                'trends bar chart',
                makeTrendsQuery(ChartDisplayType.ActionsBar),
                ['Display', 'Y-axis unit', 'Y-axis scale', 'Statistical analysis', 'Axis labels'],
            ],
            [
                'trends area graph',
                makeTrendsQuery(ChartDisplayType.ActionsAreaGraph),
                ['Display', 'Y-axis unit', 'Y-axis scale', 'Statistical analysis', 'Axis labels'],
            ],
            ['trends number', makeTrendsQuery(ChartDisplayType.BoldNumber), ['Display', 'Unit']],
            ['trends pie', makeTrendsQuery(ChartDisplayType.ActionsPie), ['Display', 'Unit']],
            ['trends table', makeTrendsQuery(ChartDisplayType.ActionsTable), ['Display', 'Unit']],
            [
                'trends bar value (horizontal)',
                makeTrendsQuery(ChartDisplayType.ActionsBarValue),
                ['Display', 'X-axis unit', 'Axis labels'],
            ],
            ['trends world map', makeTrendsQuery(ChartDisplayType.WorldMap), ['Display', 'Unit']],
            ['box plot', makeTrendsQuery(ChartDisplayType.BoxPlot), ['Display', 'Unit', 'Y-axis scale']],
            ['slope graph', makeTrendsQuery(ChartDisplayType.SlopeGraph), ['Display', 'Unit']],
            ['retention', makeRetentionQuery(), ['Display', 'On dashboards', 'Cohort labels start at']],
            ['stickiness', makeStickinessQuery(), ['Display']],
            ['lifecycle', makeLifecycleQuery(), ['Display']],
        ]

        it.each(cases)('%s shows the expected sections', async (_name, query, expectedSections) => {
            setupAndRender(query)
            await openOptionsMenu()

            expect(getSectionTitles()).toEqual(expectedSections)
        })
    })

    describe('section header tooltips', () => {
        it('renders an info tooltip on tooltip-backed headers but not on plain ones', async () => {
            setupAndRender(makeRetentionQuery())
            await openOptionsMenu()

            const tooltipHeader = screen.getByText('Cohort labels start at').closest('h5')!
            expect(tooltipHeader.querySelector('svg')).toBeInTheDocument()

            const plainHeader = screen.getByText('On dashboards').closest('h5')!
            expect(plainHeader.querySelector('svg')).not.toBeInTheDocument()
        })
    })

    describe('box plot display options', () => {
        it('only shows "Show legend" in the Display section', async () => {
            setupAndRender(makeTrendsQuery(ChartDisplayType.BoxPlot))
            await openOptionsMenu()

            const items = getDisplaySectionItems()
            expect(items).toEqual(['Show legend', 'Exclude outliers'])
        })

        it('shows unit picker and Y-axis scale but not statistical analysis', async () => {
            setupAndRender(makeTrendsQuery(ChartDisplayType.BoxPlot))
            await openOptionsMenu()

            expect(screen.getByText('Y-axis scale')).toBeInTheDocument()
            expect(screen.queryByText('Statistical analysis')).not.toBeInTheDocument()
        })
    })

    describe('slope graph display options', () => {
        it('shows the "group by time period" interval picker — grouping defines the slope', async () => {
            setupAndRender(makeTrendsQuery(ChartDisplayType.SlopeGraph))
            expect(screen.getByText(/grouped/i)).toBeInTheDocument()
        })

        it('hides the compare picker', async () => {
            setupAndRender(makeTrendsQuery(ChartDisplayType.SlopeGraph))
            expect(screen.queryByText(/Compare to|Previous period/i)).not.toBeInTheDocument()
        })

        it('shows only the legend in the Display section', async () => {
            setupAndRender(makeTrendsQuery(ChartDisplayType.SlopeGraph))
            await openOptionsMenu()

            const items = getDisplaySectionItems()
            expect(items).toEqual(['Show legend'])
            // None of the time-series-only options should leak in.
            expect(items).not.toContain('Show values on series')
            expect(items).not.toContain('Show trend lines')
            expect(items).not.toContain('Show alert threshold lines')
            expect(items).not.toContain('Show multiple Y-axes')
            expect(items).not.toContain('Show annotations')
        })

        it('hides the Y-axis scale and statistical analysis sections', async () => {
            setupAndRender(makeTrendsQuery(ChartDisplayType.SlopeGraph))
            await openOptionsMenu()

            expect(screen.queryByText('Y-axis scale')).not.toBeInTheDocument()
            expect(screen.queryByText('Statistical analysis')).not.toBeInTheDocument()
        })
    })

    describe('line graph display options', () => {
        it('shows the "group by time period" interval picker (control for the slope graph)', async () => {
            setupAndRender(makeTrendsQuery(ChartDisplayType.ActionsLineGraph))
            expect(screen.getByText(/grouped/i)).toBeInTheDocument()
        })

        it('shows multiple options in the Display section', async () => {
            setupAndRender(makeTrendsQuery(ChartDisplayType.ActionsLineGraph))
            await openOptionsMenu()

            const items = getDisplaySectionItems()
            expect(items).toContain('Show legend')
            expect(items).toContain('Show values on series')
            expect(items).toContain('Show alert threshold lines')
            expect(items).toContain('Show trend lines')
        })

        it('shows Y-axis scale section', async () => {
            setupAndRender(makeTrendsQuery(ChartDisplayType.ActionsLineGraph))
            await openOptionsMenu()

            expect(screen.getByText('Y-axis scale')).toBeInTheDocument()
        })

        it('removes axis label option count after clearing a committed label', async () => {
            setupAndRender(makeTrendsQuery(ChartDisplayType.ActionsLineGraph, { xAxisLabel: 'Signup date' }))

            const optionsButton = screen.getAllByRole('button', { name: /Options/ })[0]
            expect(optionsButton).toHaveTextContent(/\(1\)/)

            await openOptionsMenu()
            const input = await screen.findByPlaceholderText('X-axis label')
            await userEvent.clear(input)
            expect(optionsButton).toHaveTextContent(/\(1\)/)

            fireEvent.blur(input)
            await waitFor(() => {
                expect(optionsButton).not.toHaveTextContent(/\(1\)/)
            })
        })
    })
})

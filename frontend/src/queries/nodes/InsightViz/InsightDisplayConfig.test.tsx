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

function makeStickinessQuery(display?: ChartDisplayType): StickinessQuery {
    return {
        kind: NodeKind.StickinessQuery,
        series: [...pageviewSeries],
        stickinessFilter: { display },
    }
}

function makeLifecycleQuery(): LifecycleQuery {
    return {
        kind: NodeKind.LifecycleQuery,
        series: [...pageviewSeries],
        lifecycleFilter: { showLegend: true },
    }
}

function normalizeText(text: string | null | undefined): string {
    return text?.replace(/\s+/g, ' ').trim() ?? ''
}

function getPanel(): HTMLElement {
    return screen.getByTestId('insight-display-options-panel')
}

function getTabLabels(): string[] {
    return within(getPanel())
        .queryAllByRole('tab')
        .map((tab) => normalizeText(tab.textContent))
}

async function openTab(label: string): Promise<void> {
    const tab = within(getPanel())
        .getAllByRole('tab')
        .find((el) => normalizeText(el.textContent).startsWith(label))!
    await userEvent.click(tab)
}

function getSectionTitles(): string[] {
    return within(getPanel())
        .queryAllByRole('heading', { level: 5 })
        .map((h) => normalizeText(h.textContent))
}

async function openOptionsMenu(): Promise<void> {
    const optionsButtons = screen.getAllByLabelText('Options')
    await userEvent.click(optionsButtons[0])
}

function getSectionItems(dataAttr: string): string[] {
    const section = screen.getByTestId(dataAttr).closest('section')!
    return within(section)
        .queryAllByRole('listitem')
        .map((li) => normalizeText(li.textContent))
        .filter(Boolean)
}

function getDisplaySectionItems(): string[] {
    return getSectionItems('options-display-section')
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

    describe('Options panel tabs and sections per insight/chart type', () => {
        type Expected = {
            tabs: string[]
            sections: Partial<Record<string, string[]>>
            displayItems?: string[]
            overlayItems?: string[]
        }
        const lineOverlays = [
            'Show trend lines',
            'Show moving average',
            'Show confidence intervals',
            'Show alert threshold lines',
        ]
        const cases: [string, InsightQueryNode, Expected][] = [
            [
                'trends line graph',
                makeTrendsQuery(ChartDisplayType.ActionsLineGraph),
                {
                    tabs: ['General', 'Axes', 'Lines'],
                    sections: {
                        General: ['Unit', 'Color customization by'],
                        Axes: ['X-axis', 'Y-axis'],
                        Lines: ['Style', 'Overlays'],
                    },
                    displayItems: ['Show values on series', 'Show annotations', 'Show legendBottom'],
                    overlayItems: lineOverlays,
                },
            ],
            [
                'trends bar chart',
                makeTrendsQuery(ChartDisplayType.ActionsBar),
                {
                    tabs: ['General', 'Axes', 'Lines'],
                    sections: {
                        General: ['Unit'],
                        Axes: ['X-axis', 'Y-axis'],
                        Lines: ['Overlays'],
                    },
                    displayItems: [
                        'Show values on series',
                        'Show as % of total',
                        'Show annotations',
                        'Show legendBottom',
                    ],
                    overlayItems: lineOverlays,
                },
            ],
            [
                'trends area graph',
                makeTrendsQuery(ChartDisplayType.ActionsAreaGraph),
                {
                    tabs: ['General', 'Axes', 'Lines'],
                    sections: {
                        General: ['Unit'],
                        Axes: ['X-axis', 'Y-axis'],
                        Lines: ['Style', 'Overlays'],
                    },
                    displayItems: [
                        'Show values on series',
                        'Show as % of total',
                        'Show annotations',
                        'Show legendBottom',
                    ],
                },
            ],
            [
                'trends number',
                makeTrendsQuery(ChartDisplayType.BoldNumber),
                { tabs: [], sections: { General: ['Unit'] } },
            ],
            [
                'trends pie',
                makeTrendsQuery(ChartDisplayType.ActionsPie),
                {
                    tabs: [],
                    sections: { General: ['Unit'] },
                    displayItems: [
                        'Show values on series',
                        'Show as % of total',
                        'Show names on slices',
                        'Show total below chart',
                        // In-chart legend toggle + position select ("Bottom" is the prospective default)
                        'Show legendBottom',
                    ],
                },
            ],
            [
                'trends donut',
                makeTrendsQuery(ChartDisplayType.ActionsDonut),
                {
                    tabs: [],
                    sections: { General: ['Unit'] },
                    displayItems: [
                        'Show values on series',
                        'Show as % of total',
                        'Show names on slices',
                        'Show total in center',
                        'Show legendBottom',
                    ],
                },
            ],
            [
                'trends table',
                makeTrendsQuery(ChartDisplayType.ActionsTable),
                { tabs: [], sections: { General: ['Unit'] } },
            ],
            [
                'trends bar value (horizontal)',
                makeTrendsQuery(ChartDisplayType.ActionsBarValue),
                {
                    tabs: ['General', 'Axes'],
                    sections: { General: ['Unit'], Axes: ['X-axis', 'Y-axis'] },
                    displayItems: ['Show values on series'],
                },
            ],
            [
                'trends world map',
                makeTrendsQuery(ChartDisplayType.WorldMap),
                { tabs: [], sections: { General: ['Unit'] } },
            ],
            [
                'box plot',
                makeTrendsQuery(ChartDisplayType.BoxPlot),
                {
                    tabs: ['General', 'Axes'],
                    sections: { General: ['Unit'], Axes: ['Y-axis'] },
                    displayItems: ['Show legend', 'Exclude outliers'],
                },
            ],
            [
                'slope graph',
                makeTrendsQuery(ChartDisplayType.SlopeGraph),
                { tabs: [], sections: { General: ['Unit'] }, displayItems: ['Show legend'] },
            ],
            [
                'retention',
                makeRetentionQuery(),
                {
                    tabs: [],
                    sections: { General: ['On dashboards', 'Cohort labels start at', 'Style', 'Overlays'] },
                    overlayItems: ['Show trend lines'],
                },
            ],
            [
                'stickiness',
                makeStickinessQuery(),
                {
                    tabs: [],
                    sections: { General: ['Y-axis', 'Style'] },
                    displayItems: ['Show values on series', 'Show legendBottom'],
                },
            ],
            ['stickiness table', makeStickinessQuery(ChartDisplayType.ActionsTable), { tabs: [], sections: {} }],
            [
                'lifecycle',
                makeLifecycleQuery(),
                {
                    tabs: [],
                    sections: { General: [] },
                    displayItems: [
                        'Stack bars',
                        'Show values on series',
                        'Show percentages on series',
                        'Show legendRight',
                    ],
                },
            ],
        ]

        it.each(cases)('%s shows the expected tabs, sections and items', async (_name, query, expected) => {
            setupAndRender(query)

            if (Object.keys(expected.sections).length === 0) {
                expect(screen.queryByLabelText('Options')).not.toBeInTheDocument()
                return
            }

            await openOptionsMenu()
            expect(getTabLabels()).toEqual(expected.tabs)

            for (const [tab, titles] of Object.entries(expected.sections)) {
                if (expected.tabs.length > 0) {
                    await openTab(tab)
                }
                expect(getSectionTitles()).toEqual(titles)
                if (tab === 'General') {
                    if (!expected.displayItems) {
                        expect(screen.queryByTestId('options-display-section')).not.toBeInTheDocument()
                    } else {
                        expect(getDisplaySectionItems()).toEqual(expected.displayItems)
                    }
                }
                if ((tab === 'Lines' || expected.tabs.length === 0) && expected.overlayItems) {
                    expect(getSectionItems('options-overlays-section')).toEqual(expected.overlayItems)
                }
            }
        })
    })

    describe('options count', () => {
        it('sums non-default options across every tab, but keeps tab labels fixed', async () => {
            setupAndRender(
                makeTrendsQuery(ChartDisplayType.ActionsLineGraph, {
                    showValuesOnSeries: true,
                    showAnnotations: false,
                    yAxisScaleType: 'log10',
                    showTrendLines: true,
                })
            )
            expect(screen.getAllByLabelText('Options')[0]).toHaveTextContent(/\(4\)/)

            await openOptionsMenu()
            expect(getTabLabels()).toEqual(['General', 'Axes', 'Lines'])
        })
    })

    describe('overlays tab', () => {
        it('shows the moving average window and confidence level inputs only while their overlay is on', async () => {
            setupAndRender(
                makeTrendsQuery(ChartDisplayType.ActionsLineGraph, {
                    showMovingAverage: true,
                    showConfidenceIntervals: true,
                })
            )
            await openOptionsMenu()
            await openTab('Lines')

            expect(getSectionItems('options-overlays-section')).toEqual([
                'Show trend lines',
                'Show moving average',
                'Intervalsdays',
                'Show confidence intervals',
                'Confidence level%',
                'Show alert threshold lines',
            ])
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

    describe('line graph display options', () => {
        it('shows the "group by time period" interval picker (control for the slope graph)', async () => {
            setupAndRender(makeTrendsQuery(ChartDisplayType.ActionsLineGraph))
            expect(screen.getByText(/grouped/i)).toBeInTheDocument()
        })

        it('removes axis label option count after clearing a committed label', async () => {
            setupAndRender(makeTrendsQuery(ChartDisplayType.ActionsLineGraph, { xAxisLabel: 'Signup date' }))

            const optionsButton = screen.getAllByLabelText('Options')[0]
            expect(optionsButton).toHaveTextContent(/\(1\)/)

            await openOptionsMenu()
            await openTab('Axes')
            const input = await screen.findByTestId('trends-x-axis-label-input')
            await userEvent.clear(input)
            expect(optionsButton).toHaveTextContent(/\(1\)/)

            fireEvent.blur(input)
            await waitFor(() => {
                expect(optionsButton).not.toHaveTextContent(/\(1\)/)
            })
        })
    })

    describe('in-chart legend position options', () => {
        it('keeps the "Show legend" checkbox and adds a position select on the same row', async () => {
            setupAndRender(makeTrendsQuery(ChartDisplayType.ActionsLineGraph))
            await openOptionsMenu()

            const legendItem = getDisplaySectionItems().find((item) => item.includes('Show legend'))
            expect(legendItem).toBeTruthy()
            // legend is off, no saved position → shows 'Bottom' as the prospective default
            expect(legendItem).toContain('Bottom')
        })

        it.each([
            ['trends bar', () => makeTrendsQuery(ChartDisplayType.ActionsBar)],
            ['trends unstacked bar', () => makeTrendsQuery(ChartDisplayType.ActionsUnstackedBar)],
            ['trends pie', () => makeTrendsQuery(ChartDisplayType.ActionsPie)],
            ['stickiness line', () => makeStickinessQuery(ChartDisplayType.ActionsLineGraph)],
            ['stickiness bar', () => makeStickinessQuery(ChartDisplayType.ActionsBar)],
            ['lifecycle', () => makeLifecycleQuery()],
        ])('adds the legend position select for %s', async (_desc, makeQuery) => {
            setupAndRender(makeQuery())
            await openOptionsMenu()

            const legendItem = getDisplaySectionItems().find((item) => item.includes('Show legend'))
            expect(legendItem).toBeTruthy()
            // Lifecycle sets showLegend:true (no saved position → 'Right'); others have legend off (→ 'Bottom').
            expect(legendItem).toMatch(/Bottom|Right/)
        })

        it('keeps the plain "Show legend" checkbox for the aggregated bar-value chart', async () => {
            setupAndRender(makeTrendsQuery(ChartDisplayType.ActionsBarValue))
            await openOptionsMenu()

            // The aggregated bar-value layout has no in-chart legend, so it must not get a position select.
            const items = getDisplaySectionItems()
            expect(items.some((item) => item.includes('Bottom'))).toBe(false)
        })
    })
})

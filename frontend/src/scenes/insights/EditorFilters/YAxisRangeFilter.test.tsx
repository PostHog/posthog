import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { BindLogic, Provider } from 'kea'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { useMocks } from '~/mocks/jest'
import { NodeKind, TrendsFilter, TrendsQuery } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { BaseMathType, ChartDisplayType, InsightShortId } from '~/types'

import { YAxisRangeFilter } from './YAxisRangeFilter'

const insightProps = { dashboardItemId: '123' as InsightShortId }

function makeQuery(trendsFilter: TrendsFilter, display = ChartDisplayType.ActionsLineGraph): TrendsQuery {
    return {
        kind: NodeKind.TrendsQuery,
        series: [{ kind: NodeKind.EventsNode, event: '$pageview', math: BaseMathType.TotalCount }],
        trendsFilter: { display, ...trendsFilter },
    }
}

describe('YAxisRangeFilter', () => {
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

    afterEach(() => cleanup())

    function setup(trendsFilter: TrendsFilter, display?: ChartDisplayType): HTMLElement {
        insightLogic(insightProps).mount()
        insightDataLogic(insightProps).mount()
        const vizDataLogic = insightVizDataLogic(insightProps)
        vizDataLogic.mount()
        vizDataLogic.actions.updateQuerySource(makeQuery(trendsFilter, display))

        return render(
            <Provider>
                <BindLogic logic={insightLogic} props={insightProps}>
                    <YAxisRangeFilter />
                </BindLogic>
            </Provider>
        ).container
    }

    const control = (container: HTMLElement, attr: string): HTMLElement =>
        container.querySelector<HTMLElement>(`[data-attr="${attr}"]`)!

    const committedFilter = (): TrendsFilter =>
        (insightVizDataLogic(insightProps).values.querySource as TrendsQuery).trendsFilter ?? {}

    // "Begin at zero" and the minimum both set the axis floor, so exactly one is live at a time.
    // Wire the reason to the wrong control and the toggle is unusable, since it is on by default.
    // Every row carries a display, including `undefined`: jest passes a `done` callback in place of
    // an argument a shorter row doesn't supply, and the case then times out waiting on it.
    it.each<[string, TrendsFilter, { toggle: boolean; min: boolean; max: boolean }, ChartDisplayType | undefined]>([
        ['begin at zero is on by default', {}, { toggle: false, min: true, max: false }, undefined],
        ['begin at zero is off', { yAxisStartAtZero: false }, { toggle: false, min: false, max: false }, undefined],
        ['a logarithmic scale', { yAxisScaleType: 'log10' }, { toggle: true, min: true, max: true }, undefined],
        [
            'percentages are shown',
            { showPercentStackView: true },
            { toggle: true, min: true, max: true },
            // Percent stacking is offered on bar, area and pie only, so an area graph is the one
            // display where it and the range controls are both reachable.
            ChartDisplayType.ActionsAreaGraph,
        ],
    ])('disables the right controls when %s', (_name, trendsFilter, expected, display) => {
        const container = setup(trendsFilter, display)
        expect(control(container, 'trends-y-axis-start-at-zero')).toHaveProperty('disabled', expected.toggle)
        expect(control(container, 'trends-y-axis-min-input')).toHaveProperty('disabled', expected.min)
        expect(control(container, 'trends-y-axis-max-input')).toHaveProperty('disabled', expected.max)
    })

    // An emptied number input reports NaN. Committing that leaves a bound the chart ignores but the
    // Options badge still counts, so the user sees an option they cannot clear, and it reaches the
    // saved insight as null. `toBeUndefined` separates that from the bound simply not clearing.
    it('commits undefined rather than NaN when a bound is cleared', async () => {
        const container = setup({ yAxisStartAtZero: false, yAxisMin: 40 })
        const input = control(container, 'trends-y-axis-min-input')

        fireEvent.change(input, { target: { value: '' } })
        fireEvent.blur(input)

        await waitFor(() => expect(committedFilter().yAxisMin).toBeUndefined())
    })

    // The chart falls back to its automatic range on an inverted pair, so the message explains a
    // real effect. While the minimum is disabled there is no such effect to explain.
    it.each<[string, TrendsFilter, boolean]>([
        ['the minimum applies', { yAxisStartAtZero: false, yAxisMin: 80, yAxisMax: 10 }, true],
        ['begin at zero holds the minimum back', { yAxisMin: 80, yAxisMax: 10 }, false],
    ])('shows the inverted-range message only while %s', (_name, trendsFilter, shown) => {
        const container = setup(trendsFilter)
        expect(container.textContent?.includes('Maximum must be greater than minimum')).toBe(shown)
    })
})

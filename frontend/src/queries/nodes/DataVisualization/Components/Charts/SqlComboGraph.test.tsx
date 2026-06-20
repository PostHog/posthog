import '@testing-library/jest-dom'

import { cleanup, configure, screen, waitFor } from '@testing-library/react'

import { setupJsdom, setupSyncRaf } from '@posthog/quill-charts/testing'

import { ChartSettings } from '~/queries/schema/schema-general'
import {
    type DataVizFixture,
    buildDataVisualizationQuery,
    MONTHS,
    renderDataVisualization,
} from '~/test/insight-testing'
import { ChartDisplayType } from '~/types'

// Neither timeout is set globally (jest.setup leaves asyncUtilTimeout at 1s, jest.config has no
// testTimeout → 5s); this heavy ~7-logic mount needs waitFor headroom beyond 1s on contended CI.
configure({ asyncUtilTimeout: 5000 })
jest.setTimeout(15000)

let cleanupJsdom: () => void
let cleanupRaf: () => void

beforeEach(() => {
    cleanupJsdom = setupJsdom()
    cleanupRaf = setupSyncRaf()
})

afterEach(() => {
    cleanupRaf()
    cleanupJsdom()
    cleanup()
})

const twoSeries = (): DataVizFixture => ({
    columns: ['month', 'a', 'b'],
    types: [
        ['month', 'Date'],
        ['a', 'UInt64'],
        ['b', 'UInt64'],
    ],
    results: MONTHS.map((m, i) => [m, (i + 1) * 100, (i + 1) * 10]),
})

const render = (display: ChartDisplayType, chartSettings: ChartSettings): ReturnType<typeof renderDataVisualization> =>
    renderDataVisualization({
        query: buildDataVisualizationQuery({
            display,
            chartSettings: { xAxis: { column: 'month' }, ...chartSettings },
        }),
        response: twoSeries(),
    })

// Quill renders `<canvas aria-label="Chart with N data series">`; the legacy chart.js path does not.
// Each test below waits for a canvas, then asserts the quill aria-label is absent (i.e. legacy rendered).
//
// There is no `SqlComboGraph` quill component yet: combo charts (mixed bar+line/area series) and
// dual-axis charts (a series pinned to the right y-axis) aren't ported, so `LineGraph` keeps routing
// them to the legacy chart.js renderer even with the `product-analytics-quill-sql-charts` flag on.
// These tests lock that fallback in so the behavior is explicit and any future port has to update them.
describe('SqlComboGraph (combo/dual-axis fall back to legacy)', () => {
    describe('mixed bar + line/area series', () => {
        it.each([
            { name: 'a line series inside a bar chart', display: ChartDisplayType.ActionsBar, override: 'line' },
            { name: 'an area series inside a bar chart', display: ChartDisplayType.ActionsBar, override: 'area' },
            { name: 'a bar series inside a line chart', display: ChartDisplayType.ActionsLineGraph, override: 'bar' },
        ] as const)('falls back to legacy for $name', async ({ display, override }) => {
            render(display, {
                yAxis: [{ column: 'a' }, { column: 'b', settings: { display: { displayType: override } } }],
            })

            await waitFor(() => expect(document.querySelector('canvas')).toBeInTheDocument())
            expect(screen.queryByRole('img', { name: /chart with/i })).not.toBeInTheDocument()
        })
    })

    describe('dual y-axis', () => {
        it.each([ChartDisplayType.ActionsLineGraph, ChartDisplayType.ActionsBar] as const)(
            'falls back to legacy when a series targets the right axis (%s)',
            async (display) => {
                render(display, {
                    yAxis: [{ column: 'a' }, { column: 'b', settings: { display: { yAxisPosition: 'right' } } }],
                })

                await waitFor(() => expect(document.querySelector('canvas')).toBeInTheDocument())
                expect(screen.queryByRole('img', { name: /chart with/i })).not.toBeInTheDocument()
            }
        )
    })
})

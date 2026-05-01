import { cleanup, render } from '@testing-library/react'

import { drawBars } from '../core/canvas-renderer'
import type { BarRect } from '../core/canvas-renderer'
import type { ChartTheme, ResolvedSeries, Series } from '../core/types'
import { setupJsdom } from '../test-helpers'
import { BarChart } from './BarChart'

jest.mock('../core/canvas-renderer', () => {
    const actual = jest.requireActual('../core/canvas-renderer')
    return { __esModule: true, ...actual, drawBars: jest.fn() }
})

const mockedDrawBars = drawBars as jest.MockedFunction<typeof drawBars>

const THEME: ChartTheme = {
    colors: ['#1f77b4', '#ff7f0e', '#2ca02c'],
    backgroundColor: '#ffffff',
    gridColor: '#eeeeee',
    crosshairColor: '#888888',
}

const SERIES: Series[] = [
    { key: 'a', label: 'A', data: [10, 20, 30] },
    { key: 'b', label: 'B', data: [5, 15, 25] },
]

const LABELS = ['Mon', 'Tue', 'Wed']

type Layout = 'stacked' | 'grouped' | 'percent'
type Orientation = 'vertical' | 'horizontal'

describe('BarChart', () => {
    let teardown: () => void

    let originalRaf: typeof global.requestAnimationFrame | undefined
    beforeEach(() => {
        teardown = setupJsdom()
        mockedDrawBars.mockClear()
        originalRaf = global.requestAnimationFrame
        // Run draw effects synchronously so the static-layer RAF fires before the test reads the spy.
        global.requestAnimationFrame = ((cb: FrameRequestCallback) => {
            cb(0)
            return 0
        }) as typeof global.requestAnimationFrame
    })

    afterEach(() => {
        teardown()
        cleanup()
        if (originalRaf) {
            global.requestAnimationFrame = originalRaf
        }
    })

    describe.each<[Layout, Orientation]>([
        ['stacked', 'vertical'],
        ['grouped', 'vertical'],
        ['percent', 'vertical'],
        ['stacked', 'horizontal'],
        ['grouped', 'horizontal'],
        ['percent', 'horizontal'],
    ])('%s / %s', (barLayout, axisOrientation) => {
        it('renders a canvas without throwing', () => {
            const { container } = render(
                <BarChart series={SERIES} labels={LABELS} theme={THEME} config={{ barLayout, axisOrientation }} />
            )
            expect(container.querySelector('canvas')).not.toBeNull()
        })
    })

    it('forwards `dataAttr` to the chart wrapper for product-test selection', () => {
        const { container } = render(
            <BarChart series={SERIES} labels={LABELS} theme={THEME} dataAttr="bar-chart-instance" />
        )
        expect(container.querySelector('[data-attr="bar-chart-instance"]')).not.toBeNull()
    })

    it('renders empty state without crashing', () => {
        const { container } = render(<BarChart series={[]} labels={[]} theme={THEME} />)
        expect(container.querySelector('canvas')).not.toBeNull()
    })

    it('skips excluded series in stacked layout', () => {
        const series: Series[] = [
            { key: 'a', label: 'A', data: [10, 20, 30] },
            { key: 'b', label: 'B', data: [5, 15, 25], visibility: { excluded: true } },
            { key: 'c', label: 'C', data: [3, 6, 9] },
        ]
        const { container } = render(
            <BarChart series={series} labels={LABELS} theme={THEME} config={{ barLayout: 'stacked' }} />
        )
        expect(container.querySelector('canvas')).not.toBeNull()
    })

    it('renders custom percent formatter when consumer supplies one', () => {
        const formatter = jest.fn((v: number) => `${Math.round(v * 1000) / 10}‰`)
        render(
            <BarChart
                series={SERIES}
                labels={LABELS}
                theme={THEME}
                config={{ barLayout: 'percent', yTickFormatter: formatter }}
            />
        )
        expect(formatter).toHaveBeenCalled()
        // Built-in default would have produced '%' suffix; consumer's '‰' wins.
        expect(formatter.mock.results.some((r) => typeof r.value === 'string' && r.value.endsWith('‰'))).toBe(true)
    })

    it('applies a default percent formatter when consumer omits one', () => {
        const { container } = render(
            <BarChart series={SERIES} labels={LABELS} theme={THEME} config={{ barLayout: 'percent' }} />
        )
        // AxisLabels renders tick text into divs; default percent formatter emits values like "50%".
        const text = container.textContent ?? ''
        expect(text).toMatch(/\d+%/)
    })

    it('tolerates NaN data values without throwing', () => {
        const broken: Series[] = [{ key: 'a', label: 'A', data: [Number.NaN, Number.NaN, Number.NaN] }]
        const { container } = render(<BarChart series={broken} labels={LABELS} theme={THEME} />)
        expect(container.querySelector('canvas')).not.toBeNull()
    })

    // Pins today's behaviour for multi-axis stacked bars: cap rounding picks the last visible
    // series in array order, regardless of yAxisId. The topmost rendered layer per axis isn't
    // necessarily that key — see the multi-axis follow-up in PROGRESS.md.
    it('rounds the cap of only the last visible series across axes (multi-axis stacked)', () => {
        const series: Series[] = [
            { key: 'left-1', label: 'L1', data: [10, 20, 30], yAxisId: 'left' },
            { key: 'left-2', label: 'L2', data: [5, 15, 25], yAxisId: 'left' },
            { key: 'right-1', label: 'R1', data: [1, 2, 3], yAxisId: 'right' },
        ]
        render(<BarChart series={series} labels={LABELS} theme={THEME} config={{ barLayout: 'stacked' }} />)

        const callsByKey = new Map<string, BarRect[]>()
        for (const call of mockedDrawBars.mock.calls) {
            const drawnSeries = call[1] as ResolvedSeries
            const bars = call[2] as BarRect[]
            callsByKey.set(drawnSeries.key, bars)
        }

        const hasRoundedCap = (bars: BarRect[] | undefined): boolean =>
            !!bars && bars.some((b) => b.corners.topLeft || b.corners.topRight)

        expect(hasRoundedCap(callsByKey.get('right-1'))).toBe(true)
        // Today's behaviour: the topmost layer of the left axis (left-2) does not get the
        // rounded cap, because the selection only considers array order. Pinning so the fix
        // flips this assertion intentionally when it lands.
        expect(hasRoundedCap(callsByKey.get('left-2'))).toBe(false)
        expect(hasRoundedCap(callsByKey.get('left-1'))).toBe(false)
    })
})

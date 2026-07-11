import { fireEvent } from '@testing-library/react'

import type { ChartTheme } from '../../core/types'
import { renderHogChart } from '../../testing'
import { Sparkline, sparklineValueDomain } from './Sparkline'

const THEME: ChartTheme = { colors: ['#22d3ee'], backgroundColor: '#ffffff' }
const LABELS = ['Jan', 'Feb', 'Mar', 'Apr']

describe('Sparkline', () => {
    it('renders a canvas for the line chart', () => {
        const { container } = renderHogChart(<Sparkline data={[100, 200, 300, 400]} labels={LABELS} theme={THEME} />)
        expect(container.querySelector('canvas')).not.toBeNull()
    })

    it('fires onHoverIndexChange with the hovered index and -1 when leaving', () => {
        const onHover = jest.fn()
        const { chart, container } = renderHogChart(
            <Sparkline data={[100, 200, 300, 400]} labels={LABELS} theme={THEME} onHoverIndexChange={onHover} />
        )
        // Initial hoverIndex is -1, so the first subscription fire matches the "not hovering" state.
        expect(onHover).toHaveBeenCalledWith(-1)
        onHover.mockClear()

        chart.hoverAtIndex(2)
        expect(onHover).toHaveBeenLastCalledWith(2)

        const wrapper = container.querySelector('canvas')!.parentElement as HTMLElement
        fireEvent.mouseLeave(wrapper)
        expect(onHover).toHaveBeenLastCalledWith(-1)
    })

    it('fires -1 on unmount so a parent still mounted does not show a stale positive index', () => {
        const onHover = jest.fn()
        const { chart, unmount } = renderHogChart(
            <Sparkline data={[100, 200, 300]} labels={LABELS.slice(0, 3)} theme={THEME} onHoverIndexChange={onHover} />
        )
        chart.hoverAtIndex(1)
        onHover.mockClear()
        unmount()
        expect(onHover).toHaveBeenLastCalledWith(-1)
    })

    it('does not require labels — falls back to index strings', () => {
        const { container } = renderHogChart(<Sparkline data={[10, 20, 30]} theme={THEME} />)
        expect(container.querySelector('canvas')).not.toBeNull()
    })

    it.each([
        ['mixed values hug min..max', [30, 10, 20], [10, 30]],
        ['a flat non-zero series reads against a zero baseline (line at the top)', [500, 500, 500], [0, 500]],
        ['a flat zero series runs along the bottom', [0, 0, 0], [0, 1]],
        ['a flat negative series hangs from the zero baseline', [-5, -5], [-5, 0]],
        ['gaps (NaN) are ignored', [NaN, 10, NaN, 30], [10, 30]],
        ['all-NaN falls back to the scale default', [NaN, NaN], undefined],
        ['empty falls back to the scale default', [], undefined],
    ] as const)('sparklineValueDomain: %s', (_name, data, expected) => {
        expect(sparklineValueDomain([...data])).toEqual(expected)
    })
})

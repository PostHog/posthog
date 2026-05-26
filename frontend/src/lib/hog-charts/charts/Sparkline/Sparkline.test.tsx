import { fireEvent } from '@testing-library/react'

import type { ChartTheme } from '../../core/types'
import { renderHogChart, setupJsdom, setupSyncRaf } from '../../testing'
import { Sparkline } from './Sparkline'

const THEME: ChartTheme = { colors: ['#22d3ee'], backgroundColor: '#ffffff' }
const LABELS = ['Jan', 'Feb', 'Mar', 'Apr']

describe('Sparkline', () => {
    let teardownJsdom: () => void
    let teardownRaf: () => void

    beforeEach(() => {
        teardownJsdom = setupJsdom()
        teardownRaf = setupSyncRaf()
    })

    afterEach(() => {
        teardownRaf()
        teardownJsdom()
    })

    it('renders a canvas for the line chart', () => {
        const { container } = renderHogChart(<Sparkline data={[100, 200, 300, 400]} labels={LABELS} theme={THEME} />)
        expect(container.querySelector('canvas')).not.toBeNull()
    })

    it('fires onHoverIndexChange with the hovered index and -1 when leaving', () => {
        const onHover = jest.fn()
        const { chart, container } = renderHogChart(
            <Sparkline data={[100, 200, 300, 400]} labels={LABELS} theme={THEME} onHoverIndexChange={onHover} />
        )
        // Initial subscription delivers -1 (not hovering).
        expect(onHover).toHaveBeenCalledWith(-1)
        onHover.mockClear()

        chart.hoverAtIndex(2)
        expect(onHover).toHaveBeenLastCalledWith(2)

        const wrapper = container.querySelector('canvas')?.parentElement
        expect(wrapper).not.toBeNull()
        fireEvent.mouseLeave(wrapper as HTMLElement)
        expect(onHover).toHaveBeenLastCalledWith(-1)
    })

    it('does not require labels — falls back to index strings', () => {
        const { container } = renderHogChart(<Sparkline data={[10, 20, 30]} theme={THEME} />)
        expect(container.querySelector('canvas')).not.toBeNull()
    })
})

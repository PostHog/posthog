import { renderHook } from '@testing-library/react'

import type { Series } from '../types'
import { DEFAULT_MARGINS, useChartMargins } from './useChartMargins'

jest.mock('../../overlays/AxisLabels', () => ({
    measureLabelWidth: (text: string) => text.length * 10,
}))

const series: Series[] = [
    { key: 'a', label: 'A', data: [10, 20, 30] },
    { key: 'b', label: 'B', data: [5, 15, 25] },
]

const labels = ['Mon', 'Tue', 'Wed']

function render(opts: Partial<Parameters<typeof useChartMargins>[0]> = {}): ReturnType<typeof useChartMargins> {
    const { result } = renderHook(() =>
        useChartMargins({ series, labels, hideXAxis: false, hideYAxis: false, ...opts })
    )
    return result.current
}

describe('useChartMargins', () => {
    it('collapses bottom margin when hideXAxis is true', () => {
        expect(render({ hideXAxis: true }).bottom).toBe(8)
    })

    it('keeps default bottom margin otherwise', () => {
        expect(render().bottom).toBe(DEFAULT_MARGINS.bottom)
    })

    it('collapses left margin when hideYAxis is true', () => {
        expect(render({ hideYAxis: true }).left).toBe(8)
    })

    it('left margin is at least 20 when y-axis is shown', () => {
        expect(render({ series: [], labels: [] }).left).toBeGreaterThanOrEqual(20)
    })

    it('grows the right margin to at least 48 when multiple y-axes are present', () => {
        const dual: Series[] = [
            { key: 'a', label: 'A', data: [1, 2, 3] },
            { key: 'b', label: 'B', data: [4, 5, 6], yAxisId: 'right' },
        ]
        expect(render({ series: dual }).right).toBeGreaterThanOrEqual(48)
    })

    it('uses the default right margin when only one y-axis is in use', () => {
        expect(render({ labels: ['a', 'b'] }).right).toBe(DEFAULT_MARGINS.right)
    })

    it('ignores excluded series when detecting multiple y-axes', () => {
        const oneVisible: Series[] = [
            { key: 'a', label: 'A', data: [1, 2, 3] },
            { key: 'b', label: 'B', data: [4, 5, 6], yAxisId: 'right', visibility: { excluded: true } },
        ]
        expect(render({ series: oneVisible, labels: ['a', 'b'] }).right).toBeLessThan(48)
    })

    it('widens the left margin to fit long y-tick labels', () => {
        const big: Series[] = [{ key: 'a', label: 'A', data: [1_000_000_000, 2_000_000_000] }]
        const small: Series[] = [{ key: 'a', label: 'A', data: [1, 2] }]
        expect(render({ series: big }).left).toBeGreaterThan(render({ series: small }).left)
    })
})

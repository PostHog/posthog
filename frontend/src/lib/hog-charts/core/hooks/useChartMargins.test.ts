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

    describe('horizontal orientation', () => {
        it('sizes the left margin from the widest category label, not value-tick width', () => {
            const longCategoryLabels = ['shortest', 'a-considerably-longer-label']
            const shortValueData: Series[] = [{ key: 'a', label: 'A', data: [1, 2] }]
            const horizontal = render({
                series: shortValueData,
                labels: longCategoryLabels,
                axisOrientation: 'horizontal',
            })
            const vertical = render({ series: shortValueData, labels: longCategoryLabels })
            // Horizontal: left margin reflects category-label width (25 chars × 10 = 250 + padding).
            // Vertical: left margin reflects value-tick width (single-digit ticks → small).
            expect(horizontal.left).toBeGreaterThan(vertical.left)
        })

        it('sizes the right margin from the widest value tick, not category-label width', () => {
            const shortLabels = ['a', 'b']
            const bigValueData: Series[] = [{ key: 'a', label: 'A', data: [1_000_000_000, 2_000_000_000] }]
            const horizontal = render({
                series: bigValueData,
                labels: shortLabels,
                axisOrientation: 'horizontal',
            })
            const vertical = render({
                series: bigValueData,
                labels: shortLabels,
            })
            // Horizontal: bottom-axis value ticks force the right margin wider to accommodate the
            // rightmost tick's half-width. Vertical's right margin only sees the (tiny) category label.
            expect(horizontal.right).toBeGreaterThan(vertical.right)
        })
    })
})

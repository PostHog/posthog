import { renderHook } from '@testing-library/react'
import { PropsWithChildren } from 'react'

import type { Series } from '@posthog/quill-charts'

import { ResultChartSelectionContext, ResultChartPoint, useResultBarSelection } from './resultChartSelection'

describe('dashboard bar selection', () => {
    it('highlights only the selected segment and restores original colors when cleared', () => {
        const series: Series[] = [
            { key: 'new', label: 'New', type: 'bar', color: '#00ff00', data: [5, 6] },
            {
                key: 'returning',
                label: 'Returning',
                type: 'bar',
                color: '#0000ff',
                data: [7, 8],
                bars: [{ color: '#ff0000' }],
            },
        ]
        const labels = ['2026-01-01', '2026-01-02']
        let point: ResultChartPoint | undefined = { seriesKey: 'returning', label: labels[0] }
        const wrapper = ({ children }: PropsWithChildren): JSX.Element => (
            <ResultChartSelectionContext.Provider value={{ point, capturePoint: () => {}, captureCell: () => {} }}>
                {children}
            </ResultChartSelectionContext.Provider>
        )
        const { result, rerender } = renderHook(() => useResultBarSelection(series, labels, []), { wrapper })
        expect(result.current[1].bars?.[0].color).toBe('#ff0000')
        expect(result.current[1].bars?.[1].color).toContain('25%')
        expect(result.current[0].bars?.map((bar) => bar.color)).toEqual([
            'color-mix(in srgb, #00ff00 25%, transparent)',
            'color-mix(in srgb, #00ff00 25%, transparent)',
        ])
        point = { seriesKey: 'new', label: labels[1] }
        rerender()
        expect(result.current[0].bars?.[1].color).toBe('#00ff00')
        expect(result.current[1].bars?.[0].color).toContain('25%')
        point = undefined
        rerender()
        expect(result.current).toBe(series)
        expect(series[1].bars?.[0].color).toBe('#ff0000')
    })
})

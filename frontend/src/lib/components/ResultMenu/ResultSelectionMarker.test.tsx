import '@testing-library/jest-dom'

import { render } from '@testing-library/react'

import { useChartLayout } from '@posthog/quill-charts'

import { ResultChartSelectionContext, ResultChartPoint } from './resultChartSelection'
import { ResultSelectionMarker } from './ResultSelectionMarker'

jest.mock('@posthog/quill-charts', () => ({ useChartLayout: jest.fn(), ReferenceLine: () => null }))

describe('persistent dashboard point marker', () => {
    it('anchors to the selected series and stacked value across resizing, then disappears when cleared', () => {
        const layout = {
            series: [{ key: 'selected', data: [8], color: '#123456', yAxisId: 'right' }],
            labels: ['2026-01-02'],
            scales: { x: () => 120, y: () => 0, yAxes: { right: { scale: (value: number) => 100 - value * 10 } } },
            dimensions: { plotLeft: 0, plotTop: 0, plotWidth: 400, plotHeight: 200 },
            resolvePositionValue: () => 6,
            theme: { backgroundColor: '#ffffff' },
        }
        jest.mocked(useChartLayout).mockReturnValue(layout as unknown as ReturnType<typeof useChartLayout>)
        const point = { seriesKey: 'selected', label: '2026-01-02' }
        const marker = (selected?: ResultChartPoint): JSX.Element => (
            <ResultChartSelectionContext.Provider
                value={{ point: selected, capturePoint: () => {}, captureCell: () => {} }}
            >
                <ResultSelectionMarker />
            </ResultChartSelectionContext.Provider>
        )
        const { container, rerender } = render(marker(point))
        expect(container.querySelector('[data-attr="dashboard-result-selected-point"]')).toHaveStyle({
            left: '112px',
            top: '32px',
        })
        layout.scales.x = () => 200
        layout.scales.yAxes.right.scale = () => 60
        rerender(marker(point))
        expect(container.querySelector('[data-attr="dashboard-result-selected-point"]')).toHaveStyle({
            left: '192px',
            top: '52px',
        })
        rerender(marker())
        expect(container.querySelector('[data-attr="dashboard-result-selected-point"]')).not.toBeInTheDocument()
    })
})

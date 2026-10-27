import '@testing-library/jest-dom'

import { render } from '@testing-library/react'

import { findChart, getChart, setupChartTests } from '@posthog/quill-charts/testing'

import { initKeaTests } from '~/test/init'

import { Sparkline, SparklineProps } from './Sparkline'

setupChartTests()

function renderSparkline(props: SparklineProps): void {
    initKeaTests()
    render(<Sparkline {...props} />)
}

const DATA = [10, 5, 3, 30]
const LABELS = ['Mon', 'Tue', 'Wed', 'Thu']

describe('Sparkline', () => {
    it.each<{ shape: string; data: SparklineProps['data']; seriesCount: number }>([
        { shape: 'a flat number array', data: DATA, seriesCount: 1 },
        {
            shape: 'multiple time series',
            data: [
                { name: 'success', values: [1, 2, 3, 4], color: 'success' },
                { name: 'failure', values: [4, 3, 2, 1], color: 'danger' },
            ],
            seriesCount: 2,
        },
    ])('normalizes $shape into $seriesCount quill series', ({ data, seriesCount }) => {
        renderSparkline({ data, labels: LABELS })
        expect(getChart().seriesCount).toBe(seriesCount)
    })

    it('wires tooltip formatting and zero-row filtering through to the quill tooltip', async () => {
        renderSparkline({
            data: [
                { name: 'volume', values: [10, 0, 3, 30] },
                { name: 'errors', values: [2, 0, 0, 1] },
            ],
            labels: LABELS,
            type: 'line',
            hideZerosInTooltip: true,
            renderLabel: (label) => `Day: ${label}`,
            renderTooltipValue: (value) => `$${value.toFixed(2)}`,
        })
        const tooltip = await (await findChart()).hoverTooltip(2)

        expect(tooltip.label()).toBe('Day: Wed')
        expect(tooltip.value('volume')).toBe('$3.00')
        expect(tooltip.rows()).toEqual(['volume'])
    })

    it('shows a skeleton instead of a chart while loading', () => {
        renderSparkline({ data: DATA, labels: LABELS, loading: true })
        expect(document.querySelector('canvas')).toBeNull()
        expect(document.querySelector('.LemonSkeleton')).toBeTruthy()
    })
})

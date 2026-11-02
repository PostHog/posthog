import { render } from '@testing-library/react'

import type { ChartTheme } from '../../core/types'
import { Gauge } from './Gauge'
import { gaugeFraction, thresholdColor, thresholdSegments } from './gauge-geometry'

const THEME: ChartTheme = { colors: ['#00aa00'] }
const THRESHOLDS = [
    { value: 90, color: 'red' },
    { value: 70, color: 'orange' },
]

describe('Gauge', () => {
    it.each([
        ['inside the range', 25, 0.25],
        ['below the range', -10, 0],
        ['above the range', 150, 1],
    ])('gaugeFraction clamps a value %s', (_, value, expected) => {
        expect(gaugeFraction(value, 0, 100)).toBe(expected)
    })

    it.each([
        ['below every threshold', 50, 'green'],
        ['on a threshold', 70, 'orange'],
        ['above the highest threshold, whatever their order', 95, 'red'],
    ])('thresholdColor %s', (_, value, expected) => {
        expect(thresholdColor(value, THRESHOLDS, 'green')).toBe(expected)
    })

    it('splits the range into threshold segments, base color first', () => {
        expect(thresholdSegments(THRESHOLDS, 0, 100, 'green')).toEqual([
            { from: 0, to: 0.7, color: 'green' },
            { from: 0.7, to: 0.9, color: 'orange' },
            { from: 0.9, to: 1, color: 'red' },
        ])
    })

    it.each(['radial', 'bar'] as const)(
        'renders one %s meter per item with its value and threshold color',
        (variant) => {
            const { container } = render(
                <Gauge
                    variant={variant}
                    theme={THEME}
                    thresholds={THRESHOLDS}
                    items={[
                        { key: 'a', label: 'A', value: 80 },
                        { key: 'b', label: 'B', value: null },
                    ]}
                />
            )
            const meters = Array.from(container.querySelectorAll('[role="meter"]'))
            expect(meters.map((m) => m.getAttribute('aria-valuenow'))).toEqual(['80', null])
            const values = Array.from(container.querySelectorAll('[data-attr="hog-chart-gauge-value"]'))
            expect(values.map((v) => v.textContent)).toEqual(['80', 'No data'])
            expect(container.querySelectorAll('[data-attr="hog-chart-gauge-fill"]')[0].outerHTML).toContain('orange')
        }
    )

    it('fills a bar gauge in proportion to its value between min and max, named by key without a label', () => {
        const { container } = render(
            <Gauge variant="bar" theme={THEME} min={50} max={150} items={[{ key: 'cpu', value: 75 }]} />
        )
        expect(container.querySelector<HTMLElement>('[data-attr="hog-chart-gauge-fill"]')?.style.width).toBe('25%')
        expect(container.querySelector('[role="meter"]')?.getAttribute('aria-label')).toBe('cpu')
    })
})

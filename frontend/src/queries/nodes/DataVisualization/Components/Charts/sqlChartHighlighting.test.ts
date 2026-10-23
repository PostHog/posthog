import type { Series } from '@posthog/quill-charts'

import { highlightChartSeries } from './sqlChartHighlighting'

it('dims unselected bars without changing their values, ordering, or identity', () => {
    const source: Series[] = [
        {
            key: 'orders',
            label: 'Orders',
            type: 'bar',
            data: [5, 1, NaN],
            bars: [{}, { color: '#ff0000', label: 'Refunded' }],
        },
    ]
    const highlighted = highlightChartSeries(source, ['#0000ff'], (key, index) => key === 'orders' && index === 0)
    expect(highlighted[0].data).toBe(source[0].data)
    expect(highlighted[0].bars?.[0].color).toBe('#0000ff')
    expect(highlighted[0].bars?.[1]).toEqual({
        color: 'color-mix(in srgb, #ff0000 25%, transparent)',
        label: 'Refunded',
    })
    expect(source[0].bars?.[1].color).toBe('#ff0000')
    expect(highlightChartSeries(source, ['#0000ff'])).toBe(source)
})

it('keeps line and area geometry while fading the series behind selected-point overlays', () => {
    const source: Series[] = [
        { key: 'revenue', label: 'Revenue', type: 'area', color: '#ff0000', data: [4, NaN, 8], fill: { opacity: 0.4 } },
    ]
    const [highlighted] = highlightChartSeries(source, ['#0000ff'], (_, index) => index === 2)
    expect(highlighted.color).toBe('color-mix(in srgb, #ff0000 25%, transparent)')
    expect(highlighted.data).toBe(source[0].data)
    expect(highlighted.fill).toBe(source[0].fill)
})

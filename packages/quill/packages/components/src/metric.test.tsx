import { cleanup, render } from '@testing-library/react'

import { Metric, MetricDelta, MetricValue } from './metric'

// Comma-form rgba, matching what the metric insight passes (hexToRGBA); jsdom can't parse the
// space-separated `rgb(... / %)` syntax and would drop the style.
const POSITIVE = { background: 'rgba(139, 92, 246, 0.1)', foreground: 'rgb(139, 92, 246)' }
const NEGATIVE = { background: 'rgba(219, 55, 7, 0.1)', foreground: 'rgb(219, 55, 7)' }

function renderDelta(change: number, goodDirection: 'up' | 'down'): HTMLElement {
    const { container } = render(
        <Metric
            value={100}
            change={{ value: change }}
            goodDirection={goodDirection}
            positiveColor={POSITIVE}
            negativeColor={NEGATIVE}
        >
            <MetricValue />
            <MetricDelta />
        </Metric>
    )
    return container.querySelector<HTMLElement>('[data-attr="metric-change-pill"]')!
}

describe('Metric', () => {
    afterEach(cleanup)

    // Colors follow good/bad (via goodDirection), not up/down — a falling value on a
    // goodDirection="down" metric must get the positive color.
    it.each([
        ['up', 8.4, POSITIVE],
        ['up', -8.4, NEGATIVE],
        ['down', -8.4, POSITIVE],
        ['down', 8.4, NEGATIVE],
    ] as const)('goodDirection=%s change=%s applies the configured pill colors', (goodDirection, change, colors) => {
        const pill = renderDelta(change, goodDirection)
        expect(pill.style.background).toBe(colors.background)
        expect(pill.style.color).toBe(colors.foreground)
    })

    it('keeps the semantic Badge variant when no custom colors are supplied', () => {
        const { container } = render(
            <Metric value={100} change={{ value: 8.4 }}>
                <MetricValue />
                <MetricDelta />
            </Metric>
        )
        const pill = container.querySelector<HTMLElement>('[data-attr="metric-change-pill"]')
        expect(pill?.className).toContain('quill-badge--variant-success')
        expect(pill?.style.background).toBe('')
    })

    // Badge isn't a forwardRef component, so it must not be the trigger's `render` target — a revert
    // to `render={badge}` makes the pill the trigger itself and fires React's function-ref error.
    it('changeTooltip anchors the trigger on a span wrapping the pill, without ref errors', () => {
        const consoleError = jest.spyOn(console, 'error').mockImplementation(() => {})
        const { container } = render(
            <Metric value={100} change={{ value: 8.4 }} changeTooltip="vs last week">
                <MetricValue />
                <MetricDelta />
            </Metric>
        )
        const trigger = container.querySelector<HTMLElement>('[data-slot="tooltip-trigger"]')
        expect(trigger?.querySelector('[data-attr="metric-change-pill"]')).not.toBeNull()
        expect(consoleError).not.toHaveBeenCalled()
        consoleError.mockRestore()
    })

    it('size="md" renders the larger pill', () => {
        const { container } = render(
            <Metric value={100} change={{ value: 8.4 }}>
                <MetricValue />
                <MetricDelta size="md" />
            </Metric>
        )
        const pill = container.querySelector<HTMLElement>('[data-attr="metric-change-pill"]')!
        expect(pill.className).toContain('text-sm')
        expect(pill.className).toContain('px-2.5')
    })
})

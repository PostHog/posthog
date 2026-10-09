import { act, render } from '@testing-library/react'

import type { ChartTheme } from '../../core/types'
import { renderHogChart, setupJsdom, setupSyncRaf } from '../../testing'
import { MetricCard, type MetricChange } from './MetricCard'

const THEME: ChartTheme = { colors: ['#22d3ee'], backgroundColor: '#ffffff' }
const LABELS = ['Jan', 'Feb', 'Mar', 'Apr']
const POSITIVE_COLOR = { background: 'rgb(0 200 0 / 10%)', foreground: '#008800' }
const NEGATIVE_COLOR = { background: 'rgb(200 0 0 / 10%)', foreground: '#aa0000' }

describe('MetricCard', () => {
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

    describe('with sparkline (data + theme)', () => {
        it('shows the last data point and label by default', () => {
            const { container } = renderHogChart(
                <MetricCard
                    title="Total"
                    data={[100, 200, 300, 400]}
                    labels={LABELS}
                    theme={THEME}
                    formatValue={(v) => `$${Math.round(v)}`}
                />
            )
            expect(container.textContent).toContain('$400')
            expect(container.textContent).toContain('Apr')
        })

        it('renders a positive change pill when the series ends above the first non-zero value', () => {
            const { container } = renderHogChart(
                <MetricCard
                    title="Total"
                    data={[100, 200, 300, 400]}
                    labels={LABELS}
                    theme={THEME}
                    formatValue={(v) => `$${Math.round(v)}`}
                />
            )
            expect(container.textContent).toContain('+300.0%')
        })

        it('renders a negative change pill when the series ends below the first value', () => {
            const { container } = renderHogChart(
                <MetricCard
                    title="Total"
                    data={[400, 300, 200, 100]}
                    labels={LABELS}
                    theme={THEME}
                    formatValue={(v) => `$${Math.round(v)}`}
                />
            )
            expect(container.textContent).toContain('-75.0%')
        })

        it('skips the change pill when showChange is false', () => {
            const { container } = renderHogChart(
                <MetricCard title="Total" data={[100, 200]} labels={['Jan', 'Feb']} theme={THEME} showChange={false} />
            )
            expect(container.textContent).not.toContain('%')
        })

        it('omits the change pill when the first non-zero value is undefined', () => {
            const { container } = renderHogChart(
                <MetricCard title="Total" data={[0, 0, 0]} labels={['Jan', 'Feb', 'Mar']} theme={THEME} />
            )
            expect(container.textContent).not.toContain('%')
        })

        it('renders nothing when data is empty and no value is supplied', () => {
            const { container } = render(<MetricCard title="Total" data={[]} labels={[]} theme={THEME} />)
            expect(container.textContent).toBe('')
        })

        it('uses Math.abs in the denominator so a negative baseline still reads as a rise', () => {
            const { container } = renderHogChart(
                <MetricCard
                    title="Total"
                    data={[-100, 0, 100]}
                    labels={['Jan', 'Feb', 'Mar']}
                    theme={THEME}
                    formatValue={(v) => `${Math.round(v)}`}
                />
            )
            expect(container.textContent).toContain('+200.0%')
        })

        it('ignores a quick pass-through and only follows the cursor once it settles past the dwell', () => {
            jest.useFakeTimers()
            try {
                const { container, chart } = renderHogChart(
                    <MetricCard
                        title="Total"
                        data={[100, 200, 300, 400]}
                        labels={LABELS}
                        theme={THEME}
                        animationMs={0}
                        formatValue={(v) => `$${Math.round(v)}`}
                    />
                )

                // Cursor crosses a point but hasn't dwelled — headline stays at rest.
                act(() => chart.hoverAtIndex(1))
                expect(container.textContent).toContain('$400')
                expect(container.textContent).toContain('Apr')
                expect(container.textContent).not.toContain('$200')

                // Pointer settles past the dwell — now the headline follows it.
                act(() => {
                    jest.advanceTimersByTime(140)
                })
                expect(container.textContent).toContain('$200')
                expect(container.textContent).toContain('Feb')
            } finally {
                jest.useRealTimers()
            }
        })

        it('updates the headline value and label when hovering a different point', () => {
            const { container, chart } = renderHogChart(
                <MetricCard
                    title="Total"
                    data={[100, 200, 300, 400]}
                    labels={LABELS}
                    theme={THEME}
                    animationMs={0}
                    hoverIntentMs={0}
                    formatValue={(v) => `$${Math.round(v)}`}
                />
            )
            chart.hoverAtIndex(1)
            expect(container.textContent).toContain('$200')
            expect(container.textContent).toContain('Feb')
        })

        it('headlines the supplied `value` at rest while the chart still draws from `data`', () => {
            const { container, chart } = renderHogChart(
                <MetricCard
                    title="Revenue"
                    data={[100, 200, 300, 400]}
                    labels={LABELS}
                    theme={THEME}
                    animationMs={0}
                    hoverIntentMs={0}
                    value={9999}
                    formatValue={(v) => `$${Math.round(v)}`}
                />
            )
            expect(container.textContent).toContain('$9999')
            expect(container.querySelector('canvas')).not.toBeNull()
            chart.hoverAtIndex(2)
            expect(container.textContent).toContain('$300')
        })

        it('renders a supplied `change` pill fixed across hover', () => {
            const { container, chart } = renderHogChart(
                <MetricCard
                    title="Revenue"
                    data={[100, 200, 300, 400]}
                    labels={LABELS}
                    theme={THEME}
                    animationMs={0}
                    hoverIntentMs={0}
                    change={{ value: 12.5, label: '+12.5% vs. last week' }}
                    formatValue={(v) => `$${Math.round(v)}`}
                />
            )
            expect(container.textContent).toContain('+12.5% vs. last week')
            chart.hoverAtIndex(0)
            expect(container.textContent).toContain('+12.5% vs. last week')
            expect(container.textContent).not.toContain('+300.0%')
        })

        it('formats a supplied `change` via `formatChange` when no label is provided', () => {
            const { container } = renderHogChart(
                <MetricCard
                    title="Revenue"
                    data={[100, 200, 300, 400]}
                    labels={LABELS}
                    theme={THEME}
                    animationMs={0}
                    change={{ value: -8 }}
                />
            )
            expect(container.textContent).toContain('-8.0%')
        })

        it('suppresses the pill when change is null', () => {
            const { container } = renderHogChart(
                <MetricCard
                    title="Revenue"
                    data={[100, 200, 300, 400]}
                    labels={LABELS}
                    theme={THEME}
                    animationMs={0}
                    change={null}
                />
            )
            expect(container.textContent).not.toContain('%')
        })

        it('uses the supplied subtitle in place of the hover-driven label', () => {
            const { container } = renderHogChart(
                <MetricCard
                    title="Revenue"
                    data={[100, 200, 300, 400]}
                    labels={LABELS}
                    theme={THEME}
                    animationMs={0}
                    subtitle="Last 12 months"
                />
            )
            expect(container.textContent).toContain('Last 12 months')
            expect(container.textContent).not.toContain('Apr')
        })

        it('shows restingSubtitle at rest and yields to the hovered point label on hover', () => {
            const { container, chart } = renderHogChart(
                <MetricCard
                    title="Revenue"
                    data={[100, 200, 300, 400]}
                    labels={LABELS}
                    theme={THEME}
                    animationMs={0}
                    hoverIntentMs={0}
                    restingSubtitle="Avg"
                />
            )
            expect(container.textContent).toContain('Avg')
            expect(container.textContent).not.toContain('Apr')
            chart.hoverAtIndex(1)
            expect(container.textContent).toContain('Feb')
            expect(container.textContent).not.toContain('Avg')
        })

        it('lets a supplied subtitle win over restingSubtitle at rest and on hover', () => {
            const { container, chart } = renderHogChart(
                <MetricCard
                    title="Revenue"
                    data={[100, 200, 300, 400]}
                    labels={LABELS}
                    theme={THEME}
                    animationMs={0}
                    hoverIntentMs={0}
                    subtitle="Last 12 months"
                    restingSubtitle="Avg"
                />
            )
            expect(container.textContent).toContain('Last 12 months')
            expect(container.textContent).not.toContain('Avg')
            chart.hoverAtIndex(1)
            expect(container.textContent).toContain('Last 12 months')
        })

        it('with hoverChangeFromPreviousPoint, keeps the resting change but shows point-vs-previous on hover', () => {
            const { container, chart } = renderHogChart(
                <MetricCard
                    title="Revenue"
                    data={[100, 200, 300, 400]}
                    labels={LABELS}
                    theme={THEME}
                    animationMs={0}
                    hoverIntentMs={0}
                    change={{ value: 12.5, label: '+12.5% vs. prev period' }}
                    hoverChangeFromPreviousPoint
                />
            )
            expect(container.textContent).toContain('+12.5% vs. prev period')
            chart.hoverAtIndex(2) // 300 vs previous point 200 → +50%
            expect(container.textContent).toContain('+50.0%')
            expect(container.textContent).not.toContain('+12.5% vs. prev period')
        })

        it('with hoverChangeFromPreviousPoint, keeps the pill suppressed across hover when change is null', () => {
            const { container, chart } = renderHogChart(
                <MetricCard
                    title="Revenue"
                    data={[100, 200, 300, 400]}
                    labels={LABELS}
                    theme={THEME}
                    animationMs={0}
                    hoverIntentMs={0}
                    change={null}
                    hoverChangeFromPreviousPoint
                />
            )
            expect(container.textContent).not.toContain('%')
            chart.hoverAtIndex(2)
            expect(container.textContent).not.toContain('%')
        })

        it('with hoverChangeFromPreviousPoint, hides the pill when hovering the first point', () => {
            const { container, chart } = renderHogChart(
                <MetricCard
                    title="Revenue"
                    data={[100, 200, 300, 400]}
                    labels={LABELS}
                    theme={THEME}
                    animationMs={0}
                    hoverIntentMs={0}
                    change={{ value: 12.5, label: '+12.5%' }}
                    hoverChangeFromPreviousPoint
                />
            )
            chart.hoverAtIndex(0)
            expect(container.textContent).not.toContain('%')
        })
    })

    describe('number-only (no data)', () => {
        it('renders the formatted value without a sparkline', () => {
            const { container } = render(
                <MetricCard title="Revenue" value={8800} formatValue={(v) => `$${v.toLocaleString()}`} />
            )
            expect(container.textContent).toContain('Revenue')
            expect(container.textContent).toContain('$8,800')
            expect(container.querySelector('canvas')).toBeNull()
        })

        it('renders nothing when neither `value` nor `data` is supplied', () => {
            const { container } = render(<MetricCard title="Revenue" />)
            expect(container.textContent).toBe('')
        })

        it.each<{ name: string; change: MetricChange; goodDirection?: 'up' | 'down'; expectedColor: string }>([
            {
                name: 'positive change uses the positive color',
                change: { value: 12.5, label: '+12.5%' },
                expectedColor: 'rgb(0, 136, 0)',
            },
            {
                name: 'negative change uses the negative color',
                change: { value: -4.2, label: '-4.2%' },
                expectedColor: 'rgb(170, 0, 0)',
            },
            {
                name: 'negative change flips to the positive color when goodDirection is "down"',
                change: { value: -1.2, label: '-1.2%' },
                goodDirection: 'down',
                expectedColor: 'rgb(0, 136, 0)',
            },
        ])('$name', ({ change, goodDirection, expectedColor }) => {
            const { container } = render(
                <MetricCard
                    title="Revenue"
                    value={8800}
                    change={change}
                    goodDirection={goodDirection}
                    positiveColor={POSITIVE_COLOR}
                    negativeColor={NEGATIVE_COLOR}
                />
            )
            expect(container.textContent).toContain(change.label)
            const pill = container.querySelector('[data-attr="metric-card-change-pill"]') as HTMLElement | null
            expect(pill?.style.color).toBe(expectedColor)
        })

        it('points the change chevron down for a negative change', () => {
            const { container } = render(
                <MetricCard title="Revenue" value={8800} change={{ value: -4.2, label: '-4.2%' }} />
            )
            const chevron = container.querySelector('[data-attr="metric-card-change-pill"] svg')
            expect(chevron?.getAttribute('class')).toContain('rotate-180')
        })

        it('applies dataAttr to the root', () => {
            const { container } = render(<MetricCard title="Revenue" value={8800} dataAttr="metric-revenue" />)
            expect(container.querySelector('[data-attr="metric-revenue"]')).not.toBeNull()
        })
    })

    describe('inline change pill, fill, and subtitle', () => {
        it('renders the change pill exactly once with changeInline (no header duplicate)', () => {
            const { container } = renderHogChart(
                <MetricCard
                    title="Total"
                    data={[100, 200, 300, 400]}
                    labels={LABELS}
                    theme={THEME}
                    animationMs={0}
                    hoverIntentMs={0}
                    changeInline
                    change={{ value: 12.5, label: '+12.5%' }}
                />
            )
            expect(container.querySelectorAll('[data-attr="metric-card-change-pill"]')).toHaveLength(1)
        })

        it('drops the fixed sparkline height when sparklineFill is set', () => {
            const fixed = renderHogChart(
                <MetricCard
                    title="Total"
                    data={[100, 200]}
                    labels={['Jan', 'Feb']}
                    theme={THEME}
                    sparklineHeight={120}
                />
            )
            expect(
                (fixed.container.querySelector('[data-attr="metric-card-sparkline"]') as HTMLElement).style.height
            ).toBe('120px')

            const filled = renderHogChart(
                <MetricCard title="Total" data={[100, 200]} labels={['Jan', 'Feb']} theme={THEME} sparklineFill />
            )
            expect(
                (filled.container.querySelector('[data-attr="metric-card-sparkline"]') as HTMLElement).style.height
            ).toBe('')
        })

        it('renders the subtitle when provided and omits the row when empty', () => {
            const withSubtitle = renderHogChart(
                <MetricCard
                    title="Total"
                    data={[100, 200]}
                    labels={['Jan', 'Feb']}
                    theme={THEME}
                    subtitle="Last 7 days"
                />
            )
            expect(withSubtitle.container.querySelector('[data-attr="metric-card-subtitle"]')?.textContent).toBe(
                'Last 7 days'
            )

            const valueOnly = render(<MetricCard title={null} value={42} />)
            expect(valueOnly.container.querySelector('[data-attr="metric-card-subtitle"]')).toBeNull()
        })
    })
})

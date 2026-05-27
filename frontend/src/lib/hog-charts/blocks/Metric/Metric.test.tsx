import { render } from '@testing-library/react'

import type { ChartTheme } from '../../core/types'
import { renderHogChart, setupJsdom, setupSyncRaf } from '../../testing'
import { Metric } from './Metric'

const THEME: ChartTheme = { colors: ['#22d3ee'], backgroundColor: '#ffffff' }
const LABELS = ['Jan', 'Feb', 'Mar', 'Apr']
const POSITIVE_COLOR = { background: 'rgb(0 200 0 / 10%)', foreground: '#008800' }
const NEGATIVE_COLOR = { background: 'rgb(200 0 0 / 10%)', foreground: '#aa0000' }

describe('Metric', () => {
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
                <Metric
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
                <Metric
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
                <Metric
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
                <Metric title="Total" data={[100, 200]} labels={['Jan', 'Feb']} theme={THEME} showChange={false} />
            )
            expect(container.textContent).not.toContain('%')
        })

        it('omits the change pill when the first non-zero value is undefined', () => {
            const { container } = renderHogChart(
                <Metric title="Total" data={[0, 0, 0]} labels={['Jan', 'Feb', 'Mar']} theme={THEME} />
            )
            expect(container.textContent).not.toContain('%')
        })

        it('renders nothing when data is empty and no value is supplied', () => {
            const { container } = render(<Metric title="Total" data={[]} labels={[]} theme={THEME} />)
            expect(container.textContent).toBe('')
        })

        it('uses Math.abs in the denominator so a negative baseline still reads as a rise', () => {
            const { container } = renderHogChart(
                <Metric
                    title="Total"
                    data={[-100, 0, 100]}
                    labels={['Jan', 'Feb', 'Mar']}
                    theme={THEME}
                    formatValue={(v) => `${Math.round(v)}`}
                />
            )
            expect(container.textContent).toContain('+200.0%')
        })

        it('updates the headline value and label when hovering a different point', () => {
            const { container, chart } = renderHogChart(
                <Metric
                    title="Total"
                    data={[100, 200, 300, 400]}
                    labels={LABELS}
                    theme={THEME}
                    animationMs={0}
                    formatValue={(v) => `$${Math.round(v)}`}
                />
            )
            chart.hoverAtIndex(1)
            expect(container.textContent).toContain('$200')
            expect(container.textContent).toContain('Feb')
        })

        it('headlines the supplied `value` at rest while the chart still draws from `data`', () => {
            const { container, chart } = renderHogChart(
                <Metric
                    title="Revenue"
                    data={[100, 200, 300, 400]}
                    labels={LABELS}
                    theme={THEME}
                    animationMs={0}
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
                <Metric
                    title="Revenue"
                    data={[100, 200, 300, 400]}
                    labels={LABELS}
                    theme={THEME}
                    animationMs={0}
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
                <Metric
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
                <Metric
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
                <Metric
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
    })

    describe('number-only (no data)', () => {
        it('renders the formatted value without a sparkline', () => {
            const { container } = render(
                <Metric title="Revenue" value={8800} formatValue={(v) => `$${v.toLocaleString()}`} />
            )
            expect(container.textContent).toContain('Revenue')
            expect(container.textContent).toContain('$8,800')
            expect(container.querySelector('canvas')).toBeNull()
        })

        it('renders nothing when neither `value` nor `data` is supplied', () => {
            const { container } = render(<Metric title="Revenue" />)
            expect(container.textContent).toBe('')
        })

        it('renders a supplied change pill in number-only mode', () => {
            const { container } = render(
                <Metric
                    title="Revenue"
                    value={8800}
                    change={{ value: 12.5, label: '+12.5%' }}
                    positiveColor={POSITIVE_COLOR}
                    negativeColor={NEGATIVE_COLOR}
                />
            )
            expect(container.textContent).toContain('+12.5%')
            const pill = container.querySelector('.rounded-full') as HTMLElement | null
            expect(pill?.style.color).toBe('rgb(0, 136, 0)')
        })

        it('paints the pill with the negative color and a down chevron when change is negative', () => {
            const { container } = render(
                <Metric
                    title="Revenue"
                    value={8800}
                    change={{ value: -4.2, label: '-4.2%' }}
                    positiveColor={POSITIVE_COLOR}
                    negativeColor={NEGATIVE_COLOR}
                />
            )
            const pill = container.querySelector('.rounded-full') as HTMLElement | null
            expect(pill?.style.color).toBe('rgb(170, 0, 0)')
            const chevron = pill?.querySelector('svg')
            expect(chevron?.className.baseVal ?? chevron?.getAttribute('class')).toContain('rotate-180')
        })

        it('flips the pill color for a negative change when goodDirection is "down"', () => {
            const { container } = render(
                <Metric
                    title="Error rate"
                    value={0.5}
                    change={{ value: -1.2, label: '-1.2%' }}
                    goodDirection="down"
                    positiveColor={POSITIVE_COLOR}
                    negativeColor={NEGATIVE_COLOR}
                />
            )
            const pill = container.querySelector('.rounded-full') as HTMLElement | null
            expect(pill?.style.color).toBe('rgb(0, 136, 0)')
        })

        it('applies dataAttr to the root', () => {
            const { container } = render(<Metric title="Revenue" value={8800} dataAttr="metric-revenue" />)
            expect(container.querySelector('[data-attr="metric-revenue"]')).not.toBeNull()
        })
    })
})

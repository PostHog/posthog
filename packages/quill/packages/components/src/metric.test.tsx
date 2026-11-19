import { render } from '@testing-library/react'

import type { ChartTheme } from '@posthog/quill-charts'
import { setupJsdom, setupSyncRaf } from '@posthog/quill-charts/testing'

import { Metric, MetricSparkline, MetricSubtitle, MetricValue } from './metric'

const THEME: ChartTheme = { colors: ['#22d3ee'], backgroundColor: '#ffffff' }
// Raw bucket keys, the shape a caller passes to keep the sparkline's x-scale keys unique.
const KEYS = ['2025-09-01', '2025-10-01', '2025-11-01']

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

    // With no `restingSubtitle`, the subtitle shows the active label, which at rest is the last one.
    it('renders the active label through formatLabel', () => {
        const { container } = render(
            <Metric data={[1, 2, 3]} labels={KEYS} formatLabel={(label) => `bucket ${label}`} theme={THEME}>
                <MetricSubtitle />
            </Metric>
        )
        expect(container.textContent).toContain('bucket 2025-11-01')
    })

    it('colors the resting headline by the shown value, not the last point', () => {
        const valueColor = jest.fn((value: number) => (value > 100 ? 'red' : 'green'))
        const { getByTestId } = render(
            <Metric value={120} data={[60, 60]} theme={THEME} valueColor={valueColor}>
                <MetricValue data-attr="headline" />
            </Metric>
        )
        expect(getByTestId('headline').style.color).toBe('red')
    })

    it('reports an error from its sparkline through onError', () => {
        jest.spyOn(console, 'error').mockImplementation(() => {})
        // Only the base `Chart` reads `axisColor`, so the error starts inside the sparkline's own boundary.
        const theme = {
            ...THEME,
            get axisColor(): string {
                throw new Error('boom')
            },
        } as ChartTheme
        const onError = jest.fn()
        render(
            <Metric data={[1, 2, 3]} theme={theme} onError={onError}>
                <MetricSparkline />
            </Metric>
        )
        expect(onError).toHaveBeenCalledWith(expect.objectContaining({ message: 'boom' }), expect.anything())
        jest.mocked(console.error).mockRestore()
    })
})

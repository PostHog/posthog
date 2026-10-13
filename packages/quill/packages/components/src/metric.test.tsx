import { render } from '@testing-library/react'

import type { ChartTheme } from '@posthog/quill-charts'
import { setupJsdom, setupSyncRaf } from '@posthog/quill-charts/testing'

import { Metric, MetricSubtitle } from './metric'

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
})

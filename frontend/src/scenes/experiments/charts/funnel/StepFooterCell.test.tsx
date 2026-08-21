import { render } from '@testing-library/react'

import { StepFooterCell } from './StepFooterCell'

describe('StepFooterCell', () => {
    it('renders nothing when the step total is missing', () => {
        // A stale band array can ask for a step past the current funnel length. The missing total
        // used to reach humanFriendlyNumber and crash the whole results view; the cell drops instead.
        const { container } = render(
            <StepFooterCell stepIndex={2} steps={['Exposure', 'Purchase']} stepTotals={[100, 40]} />
        )
        expect(container.firstChild).toBeNull()
    })
})

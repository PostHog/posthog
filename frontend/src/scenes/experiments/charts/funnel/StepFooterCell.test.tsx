import '@testing-library/jest-dom'

import { render } from '@testing-library/react'

import { StepFooterCell } from './StepFooterCell'

/** `pluralize` joins with a non-breaking space, which reads as a normal space in the UI. */
function readableText(container: HTMLElement): string {
    return (container.textContent ?? '').replace(/\s/g, ' ')
}

describe('StepFooterCell', () => {
    const steps = ['Experiment exposure', 'Signed up']
    const stepTotals = [220, 55]

    it('marks the first step count as an all-variant total, without its always-100% rate', () => {
        const { container } = render(<StepFooterCell stepIndex={0} steps={steps} stepTotals={stepTotals} />)

        const text = readableText(container)
        expect(text).toContain('All variants')
        expect(text).toContain('220 users')
        expect(text).not.toContain('%')
    })

    it('shows the conversion rate on later steps', () => {
        const { container } = render(<StepFooterCell stepIndex={1} steps={steps} stepTotals={stepTotals} />)

        expect(readableText(container)).toContain('55 users (25%)')
    })
})

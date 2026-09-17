import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { FeatureFlagNoConditionsWarning } from './FeatureFlagNoConditionsWarning'

describe('FeatureFlagNoConditionsWarning', () => {
    afterEach(() => {
        cleanup()
    })

    it('warns that a flag with zero condition sets always evaluates to false', () => {
        render(<FeatureFlagNoConditionsWarning conditionSetCount={0} />)
        expect(screen.getByText(/always evaluates to/)).toBeInTheDocument()
    })

    it('renders nothing when the flag has at least one condition set', () => {
        const { container } = render(<FeatureFlagNoConditionsWarning conditionSetCount={1} />)
        expect(container).toBeEmptyDOMElement()
    })
})

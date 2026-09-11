import { render } from '@testing-library/react'

import { BlastRadiusErrorMessage } from './BlastRadiusErrorMessage'

// Link-rendering coverage lives in scenes/insights/EmptyStates/InsightEmptyState.test.tsx, which
// tests the shared renderDetailWithLinks this delegates to.
describe('BlastRadiusErrorMessage', () => {
    it('falls back to a generic line without a detail', () => {
        const { container } = render(<BlastRadiusErrorMessage error={{ status: 500 }} pluralName="organizations" />)
        expect(container.textContent).toBe("Couldn't estimate how many organizations match.")
    })
})

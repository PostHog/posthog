import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { HealthEmptyState } from './HealthEmptyState'

describe('HealthEmptyState', () => {
    afterEach(cleanup)

    it('points a project with no events at install instead of declaring it healthy', () => {
        render(<HealthEmptyState hasIngestedEvents={false} />)

        expect(screen.getByText('Health checks have not run yet')).toBeInTheDocument()
        // LemonBanner renders the action twice for its responsive layout, so there is at least one.
        expect(screen.getAllByText('Install PostHog').length).toBeGreaterThan(0)
        expect(screen.queryByText('All systems healthy')).not.toBeInTheDocument()
    })

    it('declares a project with events healthy when no issues are found', () => {
        render(<HealthEmptyState hasIngestedEvents={true} />)

        expect(screen.getByText('All systems healthy')).toBeInTheDocument()
        expect(screen.queryByText('Install PostHog')).not.toBeInTheDocument()
    })
})

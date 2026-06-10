import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { ErrorTrackingWidgetTileFilters } from './ErrorTrackingWidgetTileFilters'

describe('ErrorTrackingWidgetTileFilters', () => {
    afterEach(() => {
        cleanup()
    })

    it('renders filter controls', () => {
        render(
            <ErrorTrackingWidgetTileFilters
                tileId={1}
                config={{ limit: 10, status: 'active', dateRange: { date_from: '-7d' } }}
                onUpdateConfig={jest.fn()}
            />
        )

        expect(screen.getByText('Last 7 days')).toBeInTheDocument()
        expect(screen.queryByRole('button', { name: 'Hide filters' })).not.toBeInTheDocument()
    })

    it('shows read-only filter values without dropdowns when onUpdateConfig is omitted', () => {
        const { container } = render(
            <ErrorTrackingWidgetTileFilters
                tileId={1}
                config={{ limit: 10, status: 'resolved', dateRange: { date_from: '-7d' } }}
                disabledReason="Read only"
            />
        )

        expect(container.querySelector('[data-attr="error-tracking-widget-tile-filters-readonly"]')).toBeInTheDocument()
        expect(screen.getByText('Last 7 days')).toBeInTheDocument()
        expect(screen.getByText('Resolved')).toBeInTheDocument()
        expect(screen.queryByRole('combobox')).not.toBeInTheDocument()
    })
})

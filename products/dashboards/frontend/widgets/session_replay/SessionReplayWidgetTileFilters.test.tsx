import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { SessionReplayWidgetTileFilters } from './SessionReplayWidgetTileFilters'

describe('SessionReplayWidgetTileFilters', () => {
    afterEach(() => {
        cleanup()
    })

    it('renders date range control', () => {
        render(
            <SessionReplayWidgetTileFilters
                tileId={42}
                config={{ limit: 10, dateRange: { date_from: '-7d' } }}
                onUpdateConfig={jest.fn()}
            />
        )

        expect(screen.getByText('Last 7 days')).toBeInTheDocument()
        expect(screen.queryByRole('button', { name: 'Hide filters' })).not.toBeInTheDocument()
    })

    it('shows read-only filter values without dropdowns when onUpdateConfig is omitted', () => {
        const { container } = render(
            <SessionReplayWidgetTileFilters
                tileId={42}
                config={{ limit: 10, dateRange: { date_from: '-30d' } }}
                disabledReason="Read only"
            />
        )

        expect(container.querySelector('[data-attr="session-replay-widget-tile-filters-readonly"]')).toBeInTheDocument()
        expect(screen.getByText('Last 30 days')).toBeInTheDocument()
        expect(screen.queryByRole('combobox')).not.toBeInTheDocument()
    })
})

import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { useValues } from 'kea'

import { DashboardsContent } from './DashboardsContent'

jest.mock('./DashboardsTable', () => ({ DashboardsTableContainer: () => <div>table-arm</div> }))
jest.mock('./DashboardsGrid', () => ({ DashboardsGrid: () => <div>grid-arm</div> }))
jest.mock('kea', () => ({ ...jest.requireActual('kea'), useValues: jest.fn() }))

function renderWithFlag(value: string | undefined): void {
    ;(useValues as jest.Mock).mockReturnValue({
        featureFlags: value === undefined ? {} : { 'dashboards-list-view': value },
    })
    render(<DashboardsContent />)
}

describe('DashboardsContent', () => {
    afterEach(cleanup)

    it.each([undefined, 'control', 'bogus'])('renders the table for variant %p', (value) => {
        renderWithFlag(value)
        expect(screen.getByText('table-arm')).toBeInTheDocument()
        expect(screen.queryByText('grid-arm')).not.toBeInTheDocument()
    })

    it('renders the grid for the grid variant', () => {
        renderWithFlag('grid')
        expect(screen.getByText('grid-arm')).toBeInTheDocument()
    })

    it('renders the table for finder until the finder arm ships', () => {
        renderWithFlag('finder')
        expect(screen.getByText('table-arm')).toBeInTheDocument()
    })
})

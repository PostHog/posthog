import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { useActions, useValues } from 'kea'

import { DashboardsGrid } from './DashboardsGrid'

jest.mock('kea', () => ({ ...jest.requireActual('kea'), useValues: jest.fn(), useActions: jest.fn() }))
jest.mock('lib/lemon-ui/Link', () => ({
    Link: ({ children }: { children: React.ReactNode }) => <span>{children}</span>,
}))

const groups = [
    { folder: 'Marketing', dashboards: [{ id: 1, name: 'Campaigns' }] },
    { folder: 'Unfiled/Dashboards', dashboards: [{ id: 2, name: 'Weekly actives' }] },
]

describe('DashboardsGrid', () => {
    afterEach(cleanup)

    beforeEach(() => {
        ;(useActions as jest.Mock).mockReturnValue({ toggleFolder: jest.fn(), moveDashboardToFolder: jest.fn() })
    })

    it('renders a header per folder and a card per dashboard', () => {
        ;(useValues as jest.Mock).mockReturnValue({
            dashboardsByFolder: groups,
            dashboardsLoading: false,
            collapsedFolders: {},
        })
        render(<DashboardsGrid />)
        expect(screen.getByText('Marketing')).toBeInTheDocument()
        expect(screen.getByText('Campaigns')).toBeInTheDocument()
        expect(screen.getByText('Weekly actives')).toBeInTheDocument()
    })

    it('hides cards for a collapsed folder', () => {
        ;(useValues as jest.Mock).mockReturnValue({
            dashboardsByFolder: groups,
            dashboardsLoading: false,
            collapsedFolders: { Marketing: true },
        })
        render(<DashboardsGrid />)
        expect(screen.getByText('Marketing')).toBeInTheDocument()
        expect(screen.queryByText('Campaigns')).not.toBeInTheDocument()
        expect(screen.getByText('Weekly actives')).toBeInTheDocument()
    })
})

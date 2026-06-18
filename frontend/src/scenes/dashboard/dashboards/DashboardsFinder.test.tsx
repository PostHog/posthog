import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { useActions, useValues } from 'kea'

import { DashboardsFinder } from './DashboardsFinder'

jest.mock('kea', () => ({ ...jest.requireActual('kea'), useValues: jest.fn(), useActions: jest.fn() }))
jest.mock('lib/lemon-ui/Link', () => ({
    Link: ({ children }: { children: React.ReactNode }) => <span>{children}</span>,
}))

describe('DashboardsFinder', () => {
    const navigateToFolder = jest.fn()

    afterEach(cleanup)

    beforeEach(() => {
        navigateToFolder.mockClear()
        ;(useActions as jest.Mock).mockReturnValue({ navigateToFolder, moveDashboardToFolder: jest.fn() })
    })

    it('renders the breadcrumb, subfolders, and dashboards at the current folder', () => {
        ;(useValues as jest.Mock).mockReturnValue({
            currentFolderContents: { subfolders: ['Marketing/Q1'], dashboards: [{ id: 1, name: 'Campaigns' }] },
            breadcrumb: [
                { label: 'All dashboards', path: '' },
                { label: 'Marketing', path: 'Marketing' },
            ],
            dashboardsLoading: false,
        })
        render(<DashboardsFinder />)
        expect(screen.getByText('All dashboards')).toBeInTheDocument()
        expect(screen.getByText('Marketing')).toBeInTheDocument()
        expect(screen.getByText('Q1')).toBeInTheDocument()
        expect(screen.getByText('Campaigns')).toBeInTheDocument()
    })

    it('drills into a folder on click', () => {
        ;(useValues as jest.Mock).mockReturnValue({
            currentFolderContents: { subfolders: ['Marketing/Q1'], dashboards: [] },
            breadcrumb: [{ label: 'All dashboards', path: '' }],
            dashboardsLoading: false,
        })
        render(<DashboardsFinder />)
        fireEvent.click(screen.getByText('Q1'))
        expect(navigateToFolder).toHaveBeenCalledWith('Marketing/Q1')
    })
})

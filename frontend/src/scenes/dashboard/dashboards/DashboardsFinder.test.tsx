import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { useActions, useValues } from 'kea'

import { DashboardsFinder } from './DashboardsFinder'

jest.mock('kea', () => ({ ...jest.requireActual('kea'), useValues: jest.fn(), useActions: jest.fn() }))
jest.mock('lib/lemon-ui/Link', () => ({
    Link: ({ children }: { children: React.ReactNode }) => <span>{children}</span>,
}))
jest.mock('./DashboardCardMenu', () => ({ DashboardCardMenu: () => <span>menu</span> }))

describe('DashboardsFinder', () => {
    const navigateToFolder = jest.fn()
    const pasteIntoFolder = jest.fn()

    afterEach(cleanup)

    beforeEach(() => {
        navigateToFolder.mockClear()
        pasteIntoFolder.mockClear()
        ;(useActions as jest.Mock).mockReturnValue({
            navigateToFolder,
            pasteIntoFolder,
            moveDashboardToFolder: jest.fn(),
            renameDashboard: jest.fn(),
            stopRenaming: jest.fn(),
        })
    })

    function mockValues(overrides: Record<string, any>): void {
        ;(useValues as jest.Mock).mockReturnValue({
            currentFolder: '',
            clipboard: null,
            renamingDashboardId: null,
            dashboardsLoading: false,
            ...overrides,
        })
    }

    it('renders the breadcrumb, subfolders, and dashboards at the current folder', () => {
        mockValues({
            currentFolderContents: { subfolders: ['Marketing/Q1'], dashboards: [{ id: 1, name: 'Campaigns' }] },
            breadcrumb: [
                { label: 'All dashboards', path: '' },
                { label: 'Marketing', path: 'Marketing' },
            ],
        })
        render(<DashboardsFinder />)
        expect(screen.getByText('All dashboards')).toBeInTheDocument()
        expect(screen.getByText('Marketing')).toBeInTheDocument()
        expect(screen.getByText('Q1')).toBeInTheDocument()
        expect(screen.getByText('Campaigns')).toBeInTheDocument()
    })

    it('drills into a folder on click', () => {
        mockValues({
            currentFolderContents: { subfolders: ['Marketing/Q1'], dashboards: [] },
            breadcrumb: [{ label: 'All dashboards', path: '' }],
        })
        render(<DashboardsFinder />)
        fireEvent.click(screen.getByText('Q1'))
        expect(navigateToFolder).toHaveBeenCalledWith('Marketing/Q1')
    })

    it('shows a paste affordance into the current folder when the clipboard has an item', () => {
        mockValues({
            currentFolderContents: { subfolders: [], dashboards: [] },
            breadcrumb: [{ label: 'All dashboards', path: '' }],
            clipboard: { mode: 'cut', dashboardId: 1 },
            currentFolder: 'Marketing',
        })
        render(<DashboardsFinder />)
        fireEvent.click(screen.getByText('Paste into this folder'))
        expect(pasteIntoFolder).toHaveBeenCalledWith('Marketing')
    })
})

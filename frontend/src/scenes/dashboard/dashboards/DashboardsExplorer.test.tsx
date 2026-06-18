import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { useActions, useValues } from 'kea'

import { DashboardsExplorer } from './DashboardsExplorer'

jest.mock('kea', () => ({ ...jest.requireActual('kea'), useValues: jest.fn(), useActions: jest.fn() }))
jest.mock('lib/lemon-ui/Link', () => ({
    Link: ({ children }: { children: React.ReactNode }) => <span>{children}</span>,
}))
jest.mock('./DashboardCardMenu', () => ({ DashboardCardMenu: () => <span>menu</span> }))
jest.mock('./DashboardsFiltersBar', () => ({ DashboardsFiltersBar: () => <div>filters-bar</div> }))
// Pass-through the dnd wrappers so the card renders without @dnd-kit pointer wiring.
jest.mock('./dashboardsDnd', () => ({
    DashboardsDndContext: ({ children }: { children: React.ReactNode }) => <>{children}</>,
    DraggableDashboard: ({ children }: { children: React.ReactNode }) => <>{children}</>,
    DroppableFolder: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

describe('DashboardsExplorer', () => {
    const navigateToFolder = jest.fn()
    const pasteIntoFolder = jest.fn()
    const renameDashboard = jest.fn()
    const stopRenaming = jest.fn()

    afterEach(cleanup)

    beforeEach(() => {
        navigateToFolder.mockClear()
        pasteIntoFolder.mockClear()
        renameDashboard.mockClear()
        stopRenaming.mockClear()
        ;(useActions as jest.Mock).mockReturnValue({
            navigateToFolder,
            pasteIntoFolder,
            moveDashboardToFolder: jest.fn(),
            renameDashboard,
            stopRenaming,
            createFolder: jest.fn(),
        })
    })

    function mockValues(overrides: Record<string, any>): void {
        ;(useValues as jest.Mock).mockReturnValue({
            currentFolder: '',
            clipboard: null,
            renamingDashboardId: null,
            dashboardsLoading: false,
            compactedSubfolders: [],
            currentFolderContents: { subfolders: [], dashboards: [] },
            dashboards: [],
            filters: { search: '' },
            folderTree: [],
            ...overrides,
        })
    }

    it('renders the breadcrumb, subfolders, and dashboards at the current folder', () => {
        mockValues({
            currentFolderContents: { subfolders: ['Marketing/Q1'], dashboards: [{ id: 1, name: 'Campaigns' }] },
            compactedSubfolders: [{ path: 'Marketing/Q1', label: 'Q1' }],
            breadcrumb: [
                { label: 'All dashboards', path: '' },
                { label: 'Marketing', path: 'Marketing' },
            ],
        })
        render(<DashboardsExplorer />)
        expect(screen.getByText('All dashboards')).toBeInTheDocument()
        expect(screen.getByText('Marketing')).toBeInTheDocument()
        expect(screen.getByText('Q1')).toBeInTheDocument()
        expect(screen.getByText('Campaigns')).toBeInTheDocument()
    })

    it('drills into a folder on click', () => {
        mockValues({
            currentFolderContents: { subfolders: ['Marketing/Q1'], dashboards: [] },
            compactedSubfolders: [{ path: 'Marketing/Q1', label: 'Q1' }],
            breadcrumb: [{ label: 'All dashboards', path: '' }],
        })
        render(<DashboardsExplorer />)
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
        render(<DashboardsExplorer />)
        fireEvent.click(screen.getByText('Paste into this folder'))
        expect(pasteIntoFolder).toHaveBeenCalledWith('Marketing')
    })

    it('commits a rename on blur for the dashboard being renamed', () => {
        mockValues({
            currentFolderContents: { subfolders: [], dashboards: [{ id: 1, name: 'Campaigns' }] },
            breadcrumb: [{ label: 'All dashboards', path: '' }],
            renamingDashboardId: 1,
        })
        render(<DashboardsExplorer />)
        const input = screen.getByLabelText('Rename dashboard')
        fireEvent.change(input, { target: { value: 'New name' } })
        fireEvent.blur(input)
        expect(renameDashboard).toHaveBeenCalledWith(1, 'New name')
    })

    it('cancels the rename on Escape without dispatching a rename', () => {
        mockValues({
            currentFolderContents: { subfolders: [], dashboards: [{ id: 1, name: 'Campaigns' }] },
            breadcrumb: [{ label: 'All dashboards', path: '' }],
            renamingDashboardId: 1,
        })
        render(<DashboardsExplorer />)
        const input = screen.getByLabelText('Rename dashboard')
        fireEvent.change(input, { target: { value: 'Changed' } })
        fireEvent.keyDown(input, { key: 'Escape' })
        expect(stopRenaming).toHaveBeenCalled()
        expect(renameDashboard).not.toHaveBeenCalled()
    })

    it('shows a flat list of matches and hides folders when a search query is active', () => {
        mockValues({
            filters: { search: 'rev' },
            dashboards: [{ id: 7, name: 'Revenue' }],
            compactedSubfolders: [{ path: 'Marketing/Q1', label: 'Q1' }],
            currentFolderContents: { subfolders: ['Marketing/Q1'], dashboards: [] },
            breadcrumb: [{ label: 'All dashboards', path: '' }],
        })
        render(<DashboardsExplorer />)
        expect(screen.getByText('Revenue')).toBeInTheDocument()
        expect(screen.queryByText('Q1')).not.toBeInTheDocument()
    })
})

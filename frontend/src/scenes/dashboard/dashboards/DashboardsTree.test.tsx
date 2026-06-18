import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { useActions, useValues } from 'kea'

import { DashboardsTree } from './DashboardsTree'

jest.mock('kea', () => ({ ...jest.requireActual('kea'), useValues: jest.fn(), useActions: jest.fn() }))
jest.mock('lib/lemon-ui/Link', () => ({
    Link: ({ children }: { children: React.ReactNode }) => <span>{children}</span>,
}))
jest.mock('./DashboardCardMenu', () => ({ DashboardCardMenu: () => <span>menu</span> }))
jest.mock('./dashboardsDnd', () => ({
    DashboardsDndContext: ({ children }: { children: React.ReactNode }) => <>{children}</>,
    DraggableDashboard: ({ children }: { children: React.ReactNode }) => <>{children}</>,
    DroppableFolder: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

describe('DashboardsTree', () => {
    const navigateToFolder = jest.fn()
    const toggleFolder = jest.fn()

    afterEach(cleanup)

    beforeEach(() => {
        navigateToFolder.mockClear()
        toggleFolder.mockClear()
        ;(useActions as jest.Mock).mockReturnValue({
            navigateToFolder,
            toggleFolder,
            moveDashboardToFolder: jest.fn(),
            pasteIntoFolder: jest.fn(),
            renameDashboard: jest.fn(),
            stopRenaming: jest.fn(),
        })
    })

    function mockValues(overrides: Record<string, any>): void {
        ;(useValues as jest.Mock).mockReturnValue({
            folderTree: [],
            currentFolder: '',
            currentFolderContents: { subfolders: [], dashboards: [] },
            clipboard: null,
            renamingDashboardId: null,
            collapsedFolders: {},
            dashboardsLoading: false,
            ...overrides,
        })
    }

    it('renders the full folder tree (nested) and the current folder dashboards', () => {
        mockValues({
            folderTree: [
                {
                    path: 'Marketing',
                    label: 'Marketing',
                    children: [{ path: 'Marketing/Q1', label: 'Q1', children: [] }],
                },
            ],
            currentFolderContents: { subfolders: [], dashboards: [{ id: 1, name: 'Revenue' }] },
        })
        render(<DashboardsTree />)
        expect(screen.getByText('All dashboards')).toBeInTheDocument()
        expect(screen.getByText('Marketing')).toBeInTheDocument()
        expect(screen.getByText('Q1')).toBeInTheDocument()
        expect(screen.getByText('Revenue')).toBeInTheDocument()
    })

    it('navigates to a folder when its tree node is clicked', () => {
        mockValues({ folderTree: [{ path: 'Marketing', label: 'Marketing', children: [] }] })
        render(<DashboardsTree />)
        fireEvent.click(screen.getByText('Marketing'))
        expect(navigateToFolder).toHaveBeenCalledWith('Marketing')
    })

    it('collapses a node with children via the chevron without navigating', () => {
        mockValues({
            folderTree: [
                {
                    path: 'Marketing',
                    label: 'Marketing',
                    children: [{ path: 'Marketing/Q1', label: 'Q1', children: [] }],
                },
            ],
        })
        render(<DashboardsTree />)
        fireEvent.click(screen.getByLabelText('Collapse folder'))
        expect(toggleFolder).toHaveBeenCalledWith('Marketing')
        expect(navigateToFolder).not.toHaveBeenCalled()
    })
})

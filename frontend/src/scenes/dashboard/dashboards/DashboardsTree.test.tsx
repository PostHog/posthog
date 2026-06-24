import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { useActions, useValues } from 'kea'

import { DashboardsTree } from './DashboardsTree'

jest.mock('kea', () => ({ ...jest.requireActual('kea'), useValues: jest.fn(), useActions: jest.fn() }))
jest.mock('./DashboardsTable', () => ({
    DashboardsTable: ({ dashboards, folderForDashboard }: any) => (
        <div>
            {dashboards.map((dashboard: { id: number; name: string }) => (
                <span key={dashboard.id}>
                    {dashboard.name}
                    {folderForDashboard ? ` @ ${folderForDashboard(dashboard)}` : ''}
                </span>
            ))}
        </div>
    ),
}))
// Stub LemonTree: render each node (recursively) via renderItem, clickable to fire onFolderClick.
jest.mock('lib/lemon-ui/LemonTree/LemonTree', () => {
    const renderNodes = (items: any[], onFolderClick: any, renderItem: any): any =>
        items.map((item: any) => (
            <div key={item.id}>
                <div onClick={() => onFolderClick(item)}>{renderItem ? renderItem(item, item.name) : item.name}</div>
                {item.children ? renderNodes(item.children, onFolderClick, renderItem) : null}
            </div>
        ))
    return {
        LemonTree: ({ data, onFolderClick, renderItem }: any) => (
            <div>{renderNodes(data, onFolderClick, renderItem)}</div>
        ),
    }
})

describe('DashboardsTree', () => {
    const navigateToFolder = jest.fn()
    const toggleFolder = jest.fn()
    const setExpandedFolders = jest.fn()
    const reportDashboardsTreeFolderNavigated = jest.fn()

    afterEach(cleanup)

    beforeEach(() => {
        navigateToFolder.mockClear()
        toggleFolder.mockClear()
        setExpandedFolders.mockClear()
        reportDashboardsTreeFolderNavigated.mockClear()
        ;(useActions as jest.Mock).mockReturnValue({
            navigateToFolder,
            toggleFolder,
            setExpandedFolders,
            createFolder: jest.fn(),
            reportDashboardsTreeFolderNavigated,
        })
    })

    function mockValues(overrides: Record<string, any>): void {
        ;(useValues as jest.Mock).mockReturnValue({
            folderTree: [],
            currentFolder: '',
            currentSubtreeDashboards: [],
            entryByRef: {},
            expandedFolders: {},
            folderEntryByPath: {},
            folderDashboardCounts: {},
            dashboardsLoading: false,
            ...overrides,
        })
    }

    it('renders All dashboards as the root with folders nested under it, and the scoped table', () => {
        mockValues({
            folderTree: [
                {
                    path: 'Marketing',
                    label: 'Marketing',
                    children: [{ path: 'Marketing/Q1', label: 'Q1', children: [] }],
                },
            ],
            currentSubtreeDashboards: [{ id: 1, name: 'Revenue' }],
        })
        render(<DashboardsTree />)
        // "All dashboards" is the tree root; folders nest under it.
        expect(screen.getByText('All dashboards')).toBeInTheDocument()
        expect(screen.getByText('Marketing')).toBeInTheDocument()
        expect(screen.getByText('Q1')).toBeInTheDocument()
        expect(screen.getByText(/Revenue/)).toBeInTheDocument()
    })

    it('navigates to a childless folder without toggling it (it never expands)', () => {
        mockValues({ folderTree: [{ path: 'Marketing', label: 'Marketing', children: [] }] })
        render(<DashboardsTree />)
        fireEvent.click(screen.getByText('Marketing'))
        expect(navigateToFolder).toHaveBeenCalledWith('Marketing')
        expect(toggleFolder).not.toHaveBeenCalled()
        // Adoption signal fires with the folder's depth and whether it has subfolders.
        expect(reportDashboardsTreeFolderNavigated).toHaveBeenCalledWith(1, false)
    })

    it('navigates to a folder with subfolders and toggles its expansion', () => {
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
        fireEvent.click(screen.getByText('Marketing'))
        expect(navigateToFolder).toHaveBeenCalledWith('Marketing')
        expect(toggleFolder).toHaveBeenCalledWith('Marketing')
        expect(reportDashboardsTreeFolderNavigated).toHaveBeenCalledWith(1, true)
    })

    it('navigates to the root when the All dashboards node is clicked', () => {
        mockValues({ folderTree: [{ path: 'Marketing', label: 'Marketing', children: [] }] })
        render(<DashboardsTree />)
        fireEvent.click(screen.getByText('All dashboards'))
        expect(navigateToFolder).toHaveBeenCalledWith('')
        // Root is depth 0 and (here) has subfolders.
        expect(reportDashboardsTreeFolderNavigated).toHaveBeenCalledWith(0, true)
    })

    const clickExpandToggle = (container: HTMLElement): void => {
        fireEvent.click(container.querySelector('[data-attr="dashboards-tree-expand-toggle"]') as HTMLElement)
    }

    it('the expand toggle expands only folders that have subfolders (childless ones are skipped)', () => {
        mockValues({
            folderTree: [
                {
                    path: 'Marketing',
                    label: 'Marketing',
                    // Q1 is childless, so it isn't expandable and must not appear in the expanded map.
                    children: [{ path: 'Marketing/Q1', label: 'Q1', children: [] }],
                },
            ],
        })
        const { container } = render(<DashboardsTree />)
        clickExpandToggle(container)
        expect(setExpandedFolders).toHaveBeenCalledWith({ Marketing: true })
    })

    it('the toggle collapses everything when all folders are currently expanded', () => {
        mockValues({
            folderTree: [
                {
                    path: 'Marketing',
                    label: 'Marketing',
                    children: [{ path: 'Marketing/Q1', label: 'Q1', children: [] }],
                },
            ],
            expandedFolders: { Marketing: true },
        })
        const { container } = render(<DashboardsTree />)
        clickExpandToggle(container)
        expect(setExpandedFolders).toHaveBeenCalledWith({})
    })

    it('resolves each dashboard folder from entryByRef (the same source as scoping)', () => {
        mockValues({
            currentSubtreeDashboards: [
                { id: 1, name: 'Revenue' },
                { id: 2, name: 'Loose' },
            ],
            entryByRef: { '1': { path: 'Marketing/Q1/Revenue' } },
        })
        render(<DashboardsTree />)
        // A filed dashboard shows its parent folder; one with no FileSystem entry shows the Unfiled bucket
        // (Unfiled/Dashboards) — the same bucket the tree groups it under.
        expect(screen.getByText('Revenue @ Marketing/Q1')).toBeInTheDocument()
        expect(screen.getByText('Loose @ Unfiled/Dashboards')).toBeInTheDocument()
    })
})

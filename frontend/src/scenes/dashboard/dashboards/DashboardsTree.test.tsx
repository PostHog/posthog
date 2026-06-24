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
// Stub LemonTree: render each node's name (recursively) as a button that fires onFolderClick.
jest.mock('lib/lemon-ui/LemonTree/LemonTree', () => {
    const renderNodes = (items: any[], onFolderClick: any): any =>
        items.map((item: any) => (
            <div key={item.id}>
                <button onClick={() => onFolderClick(item)}>{item.name}</button>
                {item.children ? renderNodes(item.children, onFolderClick) : null}
            </div>
        ))
    return { LemonTree: ({ data, onFolderClick }: any) => <div>{renderNodes(data, onFolderClick)}</div> }
})

describe('DashboardsTree', () => {
    const navigateToFolder = jest.fn()
    const toggleFolder = jest.fn()
    const setExpandedFolders = jest.fn()

    afterEach(cleanup)

    beforeEach(() => {
        navigateToFolder.mockClear()
        toggleFolder.mockClear()
        setExpandedFolders.mockClear()
        ;(useActions as jest.Mock).mockReturnValue({
            navigateToFolder,
            toggleFolder,
            setExpandedFolders,
            createFolder: jest.fn(),
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
    })

    it('navigates to the root when the All dashboards node is clicked', () => {
        mockValues({ folderTree: [{ path: 'Marketing', label: 'Marketing', children: [] }] })
        render(<DashboardsTree />)
        fireEvent.click(screen.getByText('All dashboards'))
        expect(navigateToFolder).toHaveBeenCalledWith('')
    })

    it('"Expand all" expands only folders that have subfolders (childless ones are skipped)', () => {
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
        render(<DashboardsTree />)
        fireEvent.click(screen.getByText('Expand all'))
        expect(setExpandedFolders).toHaveBeenCalledWith({ Marketing: true })
    })

    it('collapses every folder when "Collapse all" is clicked (all currently expanded)', () => {
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
        render(<DashboardsTree />)
        fireEvent.click(screen.getByText('Collapse all'))
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
        // A filed dashboard shows its parent folder; one with no FileSystem entry shows Unfiled.
        expect(screen.getByText('Revenue @ Marketing/Q1')).toBeInTheDocument()
        expect(screen.getByText('Loose @ Unfiled')).toBeInTheDocument()
    })
})

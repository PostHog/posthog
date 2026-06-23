import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { useActions, useValues } from 'kea'

import { DashboardsTree } from './DashboardsTree'

jest.mock('kea', () => ({ ...jest.requireActual('kea'), useValues: jest.fn(), useActions: jest.fn() }))
jest.mock('./DashboardsTable', () => ({
    DashboardsTable: ({ dashboards }: { dashboards: { id: number; name: string }[] }) => (
        <div>
            {dashboards.map((dashboard) => (
                <span key={dashboard.id}>{dashboard.name}</span>
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

    afterEach(cleanup)

    beforeEach(() => {
        navigateToFolder.mockClear()
        ;(useActions as jest.Mock).mockReturnValue({ navigateToFolder, createFolder: jest.fn() })
    })

    function mockValues(overrides: Record<string, any>): void {
        ;(useValues as jest.Mock).mockReturnValue({
            folderTree: [],
            currentFolder: '',
            currentSubtreeDashboards: [],
            currentSubfolders: [],
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
        expect(screen.getByText('Revenue')).toBeInTheDocument()
    })

    it('navigates to a folder when its tree node is clicked', () => {
        mockValues({ folderTree: [{ path: 'Marketing', label: 'Marketing', children: [] }] })
        render(<DashboardsTree />)
        fireEvent.click(screen.getByText('Marketing'))
        expect(navigateToFolder).toHaveBeenCalledWith('Marketing')
    })

    it('navigates to the root when the All dashboards node is clicked', () => {
        mockValues({ folderTree: [{ path: 'Marketing', label: 'Marketing', children: [] }] })
        render(<DashboardsTree />)
        fireEvent.click(screen.getByText('All dashboards'))
        expect(navigateToFolder).toHaveBeenCalledWith('')
    })

    it('renders clickable subfolder chips in the content view and drills in on click', () => {
        mockValues({
            currentFolder: 'Marketing',
            currentSubfolders: [
                { path: 'Marketing/Q1', label: 'Q1', children: [] },
                { path: 'Marketing/Q2', label: 'Q2', children: [] },
            ],
        })
        render(<DashboardsTree />)
        expect(screen.getByText('Q2')).toBeInTheDocument()
        fireEvent.click(screen.getByText('Q1'))
        expect(navigateToFolder).toHaveBeenCalledWith('Marketing/Q1')
    })
})

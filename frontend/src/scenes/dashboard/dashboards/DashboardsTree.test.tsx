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
// Stub LemonTree: render each folder's name (recursively) as a button that fires onFolderClick.
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

    afterEach(cleanup)

    beforeEach(() => {
        navigateToFolder.mockClear()
        toggleFolder.mockClear()
        ;(useActions as jest.Mock).mockReturnValue({ navigateToFolder, toggleFolder, createFolder: jest.fn() })
    })

    function mockValues(overrides: Record<string, any>): void {
        ;(useValues as jest.Mock).mockReturnValue({
            folderTree: [],
            currentFolder: '',
            currentSubtreeDashboards: [],
            collapsedFolders: {},
            dashboardsLoading: false,
            ...overrides,
        })
    }

    it('renders the folder tree (nested) and the scoped dashboards table', () => {
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

    it('navigates to the root via the All dashboards button', () => {
        mockValues({ folderTree: [{ path: 'Marketing', label: 'Marketing', children: [] }] })
        render(<DashboardsTree />)
        fireEvent.click(screen.getByText('All dashboards'))
        expect(navigateToFolder).toHaveBeenCalledWith('')
    })
})

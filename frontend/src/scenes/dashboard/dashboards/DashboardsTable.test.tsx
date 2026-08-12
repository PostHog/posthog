import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { useActions, useValues } from 'kea'

import { AccessControlLevel } from '~/types'

import { DashboardsTable } from './DashboardsTable'

jest.mock('kea', () => ({ ...jest.requireActual('kea'), useValues: jest.fn(), useActions: jest.fn() }))
// BulkUpdateTagsButton pulls its own logic/deps that are irrelevant to the move affordances under test.
jest.mock('lib/components/BulkActions/BulkUpdateTagsButton', () => ({ BulkUpdateTagsButton: () => null }))
// The filters bar reads tag state from dashboardsLogic that this test doesn't mock; it's not under test.
jest.mock('./DashboardsFiltersBar', () => ({ DashboardsFiltersBar: () => null }))
// Render the row menu's overlay inline, so the row actions are assertable without driving a popover open.
jest.mock('lib/lemon-ui/LemonButton/More', () => ({ More: ({ overlay }: any) => <div>{overlay}</div> }))

let mockCtx: { selectedKeys: number[]; clearSelection: jest.Mock; setSelectedKeys: jest.Mock }
jest.mock('lib/lemon-ui/LemonTable', () => ({
    LemonTable: ({ bulkSelection, columns, dataSource }: any) => (
        <div>
            {bulkSelection ? bulkSelection.renderActions(mockCtx) : null}
            {dataSource.map((row: any) => (
                <div key={row.id}>{columns.at(-1).render(undefined, row)}</div>
            ))}
        </div>
    ),
}))

describe('DashboardsTable move to folder', () => {
    const moveDashboardsToFolder = jest.fn()
    const clearSelection = jest.fn()
    const setSelectedKeys = jest.fn()

    afterEach(cleanup)

    beforeEach(() => {
        jest.clearAllMocks()
        ;(useActions as jest.Mock).mockReturnValue({
            unpinDashboard: jest.fn(),
            pinDashboard: jest.fn(),
            tableSortingChanged: jest.fn(),
            showDuplicateDashboardModal: jest.fn(),
            showDeleteDashboardModal: jest.fn(),
            moveDashboardsToFolder,
        })
    })

    const renderTable = (rows: number[], selectedKeys: number[] = [], filedRows: number[] = rows): void => {
        ;(useValues as jest.Mock).mockReturnValue({
            tableSorting: null,
            filters: { search: '' },
            currentTeam: { id: 1 },
            filedDashboardIds: new Set(filedRows),
        })
        mockCtx = { selectedKeys, clearSelection, setSelectedKeys }
        render(
            <DashboardsTable
                dashboards={
                    rows.map((id) => ({
                        id,
                        name: `Dashboard ${id}`,
                        user_access_level: AccessControlLevel.Editor,
                    })) as any
                }
                dashboardsLoading={false}
            />
        )
    }

    it('offers the per-row move action and moves that dashboard', () => {
        renderTable([1])
        fireEvent.click(screen.getByText('Move to another folder'))
        expect(moveDashboardsToFolder).toHaveBeenCalledWith([1], 'single')
    })

    it('offers the bulk move action and moves the whole selection', () => {
        renderTable([1, 2], [1, 2])
        fireEvent.click(screen.getByText('Move to folder'))
        expect(moveDashboardsToFolder).toHaveBeenCalledWith([1, 2], 'bulk', setSelectedKeys)
        // Clicking hands the deselect callback over without calling it; when it does get called is
        // dashboardsLogic's business, and its tests cover that.
        expect(setSelectedKeys).not.toHaveBeenCalled()
    })

    it('says why a dashboard with no file system entry cannot be moved', () => {
        renderTable([1], [], [])
        fireEvent.click(screen.getByText('Move to another folder'))
        expect(moveDashboardsToFolder).not.toHaveBeenCalled()
    })

    it('says how many of the selection will be left behind', () => {
        renderTable([1, 2, 3], [1, 2, 3], [1])
        expect(screen.getByText('Move 1 to folder')).toBeInTheDocument()
    })

    it('disables the bulk move when nothing selected is filed anywhere', () => {
        renderTable([1, 2], [1, 2], [])
        fireEvent.click(screen.getByText('Move to folder'))
        expect(moveDashboardsToFolder).not.toHaveBeenCalled()
    })
})

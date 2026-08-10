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

// Stub LemonTable down to the two surfaces under test: the bulk-action bar (driven by a controllable
// selection context) and the actions column of each row.
let mockCtx: { selectedKeys: number[]; clearSelection: jest.Mock }
jest.mock('lib/lemon-ui/LemonTable', () => ({
    LemonTable: ({ bulkSelection, columns, dataSource }: any) => (
        <div>
            {bulkSelection ? bulkSelection.renderActions(mockCtx) : null}
            {dataSource.map((row: any) => (
                <div key={row.id}>{columns[columns.length - 1].render(undefined, row)}</div>
            ))}
        </div>
    ),
}))

describe('DashboardsTable move to folder', () => {
    const moveDashboardsToFolder = jest.fn()
    const clearSelection = jest.fn()

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
        ;(useValues as jest.Mock).mockReturnValue({
            tableSorting: null,
            filters: { search: '' },
            currentTeam: { id: 1 },
        })
    })

    // No file system entries are supplied or loaded anywhere here: that's the point. The move affordances
    // used to be gated on a preloaded entry, which left them absent for practically every dashboard.
    const renderTable = (rows: number[], selectedKeys: number[] = []): void => {
        mockCtx = { selectedKeys, clearSelection }
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
        expect(moveDashboardsToFolder).toHaveBeenCalledWith([1, 2], 'bulk')
        expect(clearSelection).toHaveBeenCalled()
    })
})

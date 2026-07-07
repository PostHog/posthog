import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { useActions, useValues } from 'kea'

import { DashboardsTable } from './DashboardsTable'

jest.mock('kea', () => ({ ...jest.requireActual('kea'), useValues: jest.fn(), useActions: jest.fn() }))
// BulkUpdateTagsButton pulls its own logic/deps that are irrelevant to the bulk-move button under test.
jest.mock('lib/components/BulkActions/BulkUpdateTagsButton', () => ({ BulkUpdateTagsButton: () => null }))
// The filters bar reads tag state from dashboardsLogic that this test doesn't mock; it's not under test.
jest.mock('./DashboardsFiltersBar', () => ({ DashboardsFiltersBar: () => null }))

// Stub LemonTable to render only the bulk-action bar, driven by a controllable selection context. The
// per-row column renders never run (no rows), so the test stays focused on the bulk Move affordance.
let mockCtx: { selectedKeys: number[]; clearSelection: jest.Mock }
jest.mock('lib/lemon-ui/LemonTable', () => ({
    LemonTable: ({ bulkSelection }: any) => (bulkSelection ? <div>{bulkSelection.renderActions(mockCtx)}</div> : null),
}))

describe('DashboardsTable bulk move', () => {
    const openMoveToModal = jest.fn()
    const reportDashboardMoveInitiated = jest.fn()
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
            openMoveToModal,
            reportDashboardMoveInitiated,
        })
        ;(useValues as jest.Mock).mockReturnValue({
            tableSorting: null,
            filters: { search: '' },
            currentTeam: { id: 1 },
            itemsByRef: {},
        })
    })

    // resolvable maps a dashboard id -> whether the tree arm's entry source resolves it (the rest fall through
    // to the empty itemsByRef and are therefore unmovable).
    const renderTable = (selectedKeys: number[], resolvable: Record<number, boolean>): void => {
        mockCtx = { selectedKeys, clearSelection }
        render(
            <DashboardsTable
                dashboards={[] as any}
                dashboardsLoading={false}
                dashboardFsEntry={(id) =>
                    resolvable[id]
                        ? ({ id: `fs-${id}`, type: 'dashboard', ref: String(id), path: 'Marketing' } as any)
                        : undefined
                }
            />
        )
    }

    it('does not move anything when no selected dashboard resolves to an entry', () => {
        renderTable([1, 2], {})
        // The button still renders (labelled plainly), but the disabled state means a click is a no-op.
        fireEvent.click(screen.getByText('Move to folder').closest('button')!)
        expect(openMoveToModal).not.toHaveBeenCalled()
        expect(reportDashboardMoveInitiated).not.toHaveBeenCalled()
    })

    it('reflects the resolvable count in the label when only some selected dashboards can be moved', () => {
        renderTable([1, 2, 3], { 1: true })
        expect(screen.getByText('Move 1 to folder')).toBeInTheDocument()
    })

    it('moves every resolvable entry and reports the bulk event on click', () => {
        renderTable([1, 2], { 1: true, 2: true })
        fireEvent.click(screen.getByText('Move to folder').closest('button')!)
        expect(reportDashboardMoveInitiated).toHaveBeenCalledWith('bulk', 2)
        expect(openMoveToModal).toHaveBeenCalledTimes(1)
        expect(openMoveToModal.mock.calls[0][0]).toHaveLength(2)
        expect(clearSelection).toHaveBeenCalled()
    })

    it('does not render the bulk move button in the control arm (no entry source)', () => {
        // Control passes no dashboardFsEntry, so the bulk "Move to folder" button must not appear — its
        // entry source is the mostly-empty sidebar store and it would render perpetually disabled.
        mockCtx = { selectedKeys: [1, 2], clearSelection }
        render(<DashboardsTable dashboards={[] as any} dashboardsLoading={false} />)
        expect(screen.queryByText('Move to folder')).not.toBeInTheDocument()
    })
})

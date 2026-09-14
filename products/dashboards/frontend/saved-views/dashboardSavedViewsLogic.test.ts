import { expectLogic } from 'kea-test-utils'

import { ApiError } from 'lib/api-error'
import { DashboardsTab, dashboardsLogic } from 'scenes/dashboard/dashboards/dashboardsLogic'

import { initKeaTests } from '~/test/init'

import * as api from '../generated/api'
import type { PaginatedDashboardSavedViewListApi } from '../generated/api.schemas'
import { DashboardListSavedView, DashboardSavedViewScope, dashboardSavedViewsLogic } from './dashboardSavedViewsLogic'

jest.mock('../generated/api')

const dashboardSavedViewsList = jest.mocked(api.dashboardSavedViewsList)

function savedView(id: string, scope: DashboardSavedViewScope): DashboardListSavedView {
    return {
        id,
        name: `View ${id}`,
        filters: {
            search: '',
            createdBy: 'All users',
            pinned: true,
            shared: false,
            tags: [],
            folder: null,
        },
        scope,
        created_at: '2026-08-27T12:00:00Z',
        updated_at: '2026-08-27T12:00:00Z',
        created_by: 1,
        can_change_scope: true,
    }
}

function page(views: DashboardListSavedView[], nextCursor: string | null): PaginatedDashboardSavedViewListApi {
    return {
        results: views,
        next: nextCursor ? `https://example.com/api/dashboard_saved_views/?cursor=${nextCursor}` : null,
        previous: null,
    }
}

describe('dashboardSavedViewsLogic', () => {
    beforeEach(() => {
        initKeaTests()
        dashboardSavedViewsList.mockReset()
    })

    it('tracks pagination separately for private and team views', async () => {
        dashboardSavedViewsList.mockImplementation(async (_, params) => {
            if (params?.scope === 'private') {
                return page([savedView('private-1', 'private')], null)
            }
            return page([savedView('team-1', 'team')], 'next-team-page')
        })

        const logic = dashboardSavedViewsLogic({ teamId: 1 })
        logic.mount()

        await expectLogic(logic)
            .toFinishAllListeners()
            .toMatchValues({
                savedViews: [savedView('private-1', 'private'), savedView('team-1', 'team')],
                savedViewsNextCursors: { private: null, team: 'next-team-page' },
            })

        expect(dashboardSavedViewsList).toHaveBeenCalledTimes(2)
        expect(dashboardSavedViewsList).toHaveBeenCalledWith('1', {
            limit: 100,
            scope: 'private',
            cursor: undefined,
        })
        expect(dashboardSavedViewsList).toHaveBeenCalledWith('1', {
            limit: 100,
            scope: 'team',
            cursor: undefined,
        })

        logic.unmount()
    })

    it('keeps pinned dashboards visible when saved views replace the Pinned tab', async () => {
        dashboardSavedViewsList.mockImplementation(async () => page([], null))
        dashboardsLogic.mount()
        dashboardsLogic.actions.setCurrentTab(DashboardsTab.Pinned)
        const logic = dashboardSavedViewsLogic({ teamId: 1 })
        logic.mount()

        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.currentTab).toBe(DashboardsTab.All)
        expect(logic.values.filters.pinned).toBe(true)

        logic.unmount()
        dashboardsLogic.unmount()
    })

    it('keeps loaded saved views available when loading another page fails', async () => {
        dashboardSavedViewsList.mockImplementation(async (_, params) => {
            if (params?.scope === 'private') {
                return page([savedView('private-1', 'private')], 'next-private-page')
            }
            return page([], null)
        })
        const logic = dashboardSavedViewsLogic({ teamId: 1 })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.loadMoreSavedViewsFailure('Could not load more saved views', new ApiError(undefined, 403))

        expectLogic(logic).toMatchValues({
            savedViews: [savedView('private-1', 'private')],
            savedViewsLoadError: false,
            savedViewsLoadMoreFailed: true,
        })

        logic.unmount()
    })

    it('unselects the active saved view when the final filter is removed', async () => {
        dashboardSavedViewsList.mockImplementation(async () => page([], null))
        const logic = dashboardSavedViewsLogic({ teamId: 1 })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        dashboardsLogic.actions.setFilters({ pinned: true, tags: ['product'] })
        logic.actions.setActiveSavedViewId('private-1')

        expectLogic(logic).toMatchValues({ activeSavedViewId: 'private-1' })
        await expectLogic(logic, () => dashboardsLogic.actions.setFilters({ pinned: false, tags: [] }))
            .toFinishAllListeners()
            .toMatchValues({ activeSavedViewId: null })

        logic.unmount()
    })

    it('restores the active saved view that matches persisted dashboard filters', async () => {
        dashboardSavedViewsList.mockImplementation(async (_, params) => {
            if (params?.scope === 'private') {
                return page([savedView('private-1', 'private')], null)
            }
            return page([], null)
        })
        dashboardsLogic.mount()
        dashboardsLogic.actions.setFilters({ pinned: true })
        const logic = dashboardSavedViewsLogic({ teamId: 1 })
        logic.mount()

        await expectLogic(logic).toFinishAllListeners().toMatchValues({ activeSavedViewId: 'private-1' })

        logic.unmount()
        dashboardsLogic.unmount()
    })
})

import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { BindLogic } from 'kea'
import { expectLogic } from 'kea-test-utils'

import { dayjs } from 'lib/dayjs'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel, DashboardTile, DashboardType, QueryBasedInsightModel } from '~/types'

import { dashboardLogic } from './dashboardLogic'
import { DashboardReloadAction } from './DashboardReloadAction'
import * as dashboardUtils from './dashboardUtils'

const CHECK_ICON_SELECTOR = 'clipPath[id="icon/check__a"]'

function makeDashboard(tileLastRefresh: string): DashboardType<QueryBasedInsightModel> {
    const insight = {
        id: 1,
        short_id: 'insight1',
        name: 'An insight',
        last_refresh: tileLastRefresh,
        query: null,
        result: [],
        filters: {},
    } as unknown as QueryBasedInsightModel

    return {
        id: 5,
        name: 'Test dashboard',
        pinned: false,
        tiles: [{ id: 1, color: null, layouts: {}, insight } as unknown as DashboardTile<QueryBasedInsightModel>],
        tags: [],
        created_at: '2020-01-01T00:00:00Z',
        last_accessed_at: '2020-01-01T00:00:00Z',
        is_shared: false,
        deleted: false,
        creation_mode: 'default',
        user_access_level: AccessControlLevel.Editor,
        filters: {},
        variables: {},
    } as unknown as DashboardType<QueryBasedInsightModel>
}

describe('DashboardReloadAction', () => {
    let getInsightWithRetrySpy: jest.SpyInstance

    beforeEach(() => {
        useMocks({
            post: {
                '/api/environments/:team_id/query/': () => [200, { results: [] }],
            },
        })
        initKeaTests()
        // The tile refresh on load fails, so the tile keeps its old `last_refresh`
        getInsightWithRetrySpy = jest
            .spyOn(dashboardUtils, 'getInsightWithRetry')
            .mockRejectedValue(new Error('Queries are a little too busy right now.'))
    })

    afterEach(() => {
        getInsightWithRetrySpy.mockRestore()
        cleanup()
    })

    async function renderAction(tileLastRefresh: string): Promise<ReturnType<typeof dashboardLogic.build>> {
        const dashboard = makeDashboard(tileLastRefresh)
        const props = { id: dashboard.id, dashboard }
        const logic = dashboardLogic(props)
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        // A teammate's refresh writes the shared `Dashboard.last_refresh`, which starts the block window
        await expectLogic(logic, () => {
            logic.actions.updateDashboardLastRefresh(dayjs())
        }).toFinishAllListeners()

        render(
            <BindLogic logic={dashboardLogic} props={props}>
                <DashboardReloadAction />
            </BindLogic>
        )

        return logic
    }

    it('keeps the refresh button usable when the tiles are stale', async () => {
        const logic = await renderAction(dayjs().subtract(7, 'hours').toISOString())

        expect(logic.values.itemsLoading).toBe(false)
        expect(screen.getByRole('button', { name: /refresh/i })).not.toHaveAttribute('aria-disabled', 'true')
        expect(screen.queryByText(/next bulk refresh possible/i)).not.toBeInTheDocument()
        expect(document.querySelector(CHECK_ICON_SELECTOR)).not.toBeInTheDocument()

        logic.unmount()
    })

    it('blocks the refresh button when the tiles are fresh', async () => {
        const logic = await renderAction(dayjs().toISOString())

        expect(logic.values.itemsLoading).toBe(false)
        expect(screen.getByRole('button', { name: /refresh/i })).toHaveAttribute('aria-disabled', 'true')
        expect(document.querySelector(CHECK_ICON_SELECTOR)).toBeInTheDocument()

        logic.unmount()
    })
})

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { DropdownMenu, DropdownMenuContent } from 'lib/ui/DropdownMenu/DropdownMenu'

import { useMocks } from '~/mocks/jest'
import { dashboardsModel } from '~/models/dashboardsModel'
import { initKeaTests } from '~/test/init'

import { DashboardsMenuItems } from './DashboardsMenuItems'

describe('DashboardsMenuItems', () => {
    let unmountLogic: () => void

    afterEach(() => {
        cleanup()
        unmountLogic()
    })

    function renderMenu(): void {
        initKeaTests()
        unmountLogic = dashboardsModel.mount()
        render(
            <DropdownMenu defaultOpen>
                <DropdownMenuContent>
                    <DashboardsMenuItems />
                </DropdownMenuContent>
            </DropdownMenu>
        )
    }

    it('links the pinned dashboards entry to the filtered dashboards list', async () => {
        useMocks({
            get: { '/api/environments/:team_id/dashboards/': [200, { count: 0, next: null, results: [] }] },
        })
        renderMenu()

        const trigger = (await screen.findByText('Pinned dashboards')).closest('a')
        expect(trigger?.getAttribute('href')).toContain('/dashboard?pinned=true')
    })

    it('reports a failed load instead of staying on the loading state', async () => {
        useMocks({ get: { '/api/environments/:team_id/dashboards/': () => [500, { detail: 'nope' }] } })
        renderMenu()

        fireEvent.keyDown(await screen.findByText('Pinned dashboards'), { key: 'ArrowRight' })

        expect(await screen.findByText("Couldn't load dashboards. Reopen this menu to retry.")).toBeTruthy()
        expect(screen.queryByText('Loading...')).toBeNull()
    })
})

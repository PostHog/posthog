import '@testing-library/jest-dom'

import { cleanup, render } from '@testing-library/react'
import { BindLogic } from 'kea'

import { dayjs } from 'lib/dayjs'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel, DashboardType, QueryBasedInsightModel } from '~/types'

import { dashboardLogic } from './dashboardLogic'
import { DashboardReloadAction } from './DashboardReloadAction'

const DASHBOARD_ID = 5

const MOCK_DASHBOARD: DashboardType<QueryBasedInsightModel> = {
    id: DASHBOARD_ID,
    name: 'Test Dashboard',
    description: '',
    pinned: false,
    tiles: [],
    tags: [],
    created_at: '2020-01-01T00:00:00Z',
    created_by: null,
    last_accessed_at: '2020-01-01T00:00:00Z',
    is_shared: false,
    deleted: false,
    creation_mode: 'default',
    user_access_level: AccessControlLevel.Editor,
    filters: {},
    variables: {},
}

beforeAll(() => {
    const root = document.createElement('div')
    root.id = 'root'
    document.body.appendChild(root)
})

describe('DashboardReloadAction', () => {
    beforeEach(() => {
        localStorage.clear()
        useMocks({
            get: {
                '/api/environments/:team_id/dashboards/:id/': () => [200, MOCK_DASHBOARD],
            },
            post: {
                '/api/environments/:team_id/query/': () => [200, { results: [] }],
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    function renderAction(
        prepare?: (logic: ReturnType<typeof dashboardLogic.build>) => void
    ): ReturnType<typeof dashboardLogic.build> {
        const props = { id: DASHBOARD_ID, dashboard: MOCK_DASHBOARD }
        const logic = dashboardLogic(props)
        logic.mount()
        prepare?.(logic)
        render(
            <BindLogic logic={dashboardLogic} props={props}>
                <DashboardReloadAction />
            </BindLogic>
        )
        return logic
    }

    function refreshButton(): HTMLElement {
        return document.querySelector('[data-attr="dashboard-items-action-refresh"]') as HTMLElement
    }

    it('shows the remaining cool-down on the button and disables it during the cool-down', () => {
        const logic = renderAction((l) => l.actions.updateDashboardLastRefresh(dayjs()))

        const button = refreshButton()
        expect(button.textContent).toContain('Refresh in')
        expect(button).toHaveAttribute('aria-disabled', 'true')

        logic.unmount()
    })

    it('reads "Refresh" and stays clickable when no recent refresh gates it', () => {
        const logic = renderAction()

        const button = refreshButton()
        expect(button.textContent).toContain('Refresh')
        expect(button.textContent).not.toContain('Refresh in')
        expect(button).not.toHaveAttribute('aria-disabled', 'true')

        logic.unmount()
    })
})

import '@testing-library/jest-dom'

import { cleanup, render } from '@testing-library/react'
import { BindLogic } from 'kea'
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { DashboardEventSource } from 'lib/utils/eventUsageLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel, DashboardMode, DashboardType, QueryBasedInsightModel } from '~/types'

import { DashboardFilterBar } from './DashboardFilters'
import { dashboardLogic } from './dashboardLogic'
import { SEARCH_PARAM_FILTERS_KEY } from './dashboardUtils'

const MOCK_DASHBOARD: DashboardType<QueryBasedInsightModel> = {
    id: 5,
    name: 'Test Dashboard',
    description: 'A test dashboard',
    pinned: false,
    tiles: [],
    tags: [],
    created_at: '2020-01-01T00:00:00Z',
    created_by: {
        id: 1,
        first_name: 'Test',
        last_name: 'User',
        email: 'test@posthog.com',
        uuid: 'abc',
        distinct_id: 'test-distinct-id',
    },
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

describe('DashboardFilterBar', () => {
    beforeEach(() => {
        localStorage.clear()
        sessionStorage.clear()
        useMocks({
            get: {
                '/api/environments/:team_id/events/values': { results: [] },
                '/api/environments/:team_id/persons/properties': [],
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

    function renderFilterBar(dashboardModeSource: DashboardEventSource): ReturnType<typeof dashboardLogic.build> {
        const logic = dashboardLogic({ id: MOCK_DASHBOARD.id, dashboard: MOCK_DASHBOARD })
        logic.mount()
        logic.actions.setDashboardMode(DashboardMode.Edit, dashboardModeSource)

        render(
            <BindLogic logic={dashboardLogic} props={{ id: MOCK_DASHBOARD.id, dashboard: MOCK_DASHBOARD }}>
                <DashboardFilterBar />
            </BindLogic>
        )

        return logic
    }

    it('shows editable filter controls while editing the layout', () => {
        const logic = renderFilterBar(DashboardEventSource.SceneCommonButtons)

        expect(document.querySelector('[data-attr="date-filter"]')).toBeInTheDocument()
        expect(document.querySelector('[data-attr="date-filter"]')).toHaveAttribute('aria-disabled', 'false')
        expect(document.querySelector('[data-attr="dashboard-advanced-filters"]')).toHaveAttribute(
            'aria-disabled',
            'false'
        )

        logic.unmount()
    })

    it('marks unsaved filters with inline save actions', async () => {
        const logic = renderFilterBar(DashboardEventSource.DashboardFilters)

        await expectLogic(logic, () => {
            logic.actions.setDates('-7d', null)
        }).toFinishAllListeners()

        expect(document.querySelector('[data-attr="dashboard-filters-unsaved"]')).toBeInTheDocument()
        expect(document.querySelector('[data-attr="dashboard-save-filters"]')).toBeInTheDocument()
        expect(document.querySelector('[data-attr="dashboard-edit-mode-discard"]')).toBeInTheDocument()

        logic.unmount()
    })

    it('shows a separate save action for unsaved filters while editing the layout', async () => {
        const logic = renderFilterBar(DashboardEventSource.SceneCommonButtons)

        await expectLogic(logic, () => {
            logic.actions.setDates('-7d', null)
        }).toFinishAllListeners()

        expect(document.querySelector('[data-attr="dashboard-filters-unsaved"]')).toBeInTheDocument()
        expect(document.querySelector('[data-attr="dashboard-save-filters"]')).toBeInTheDocument()

        logic.unmount()
    })

    it('keeps unsaved filter actions visible after cancelling layout editing', async () => {
        const logic = renderFilterBar(DashboardEventSource.SceneCommonButtons)

        await expectLogic(logic, () => {
            logic.actions.setDates('-7d', null)
        }).toFinishAllListeners()

        await expectLogic(logic, () => {
            logic.actions.cancelLayoutEdit()
        }).toFinishAllListeners()

        expect(document.querySelector('[data-attr="dashboard-filters-unsaved"]')).toBeInTheDocument()
        expect(document.querySelector('[data-attr="dashboard-save-filters"]')).toBeInTheDocument()

        logic.unmount()
    })

    it('shows temporary URL filters to a viewer without save actions', () => {
        router.actions.push('/', {
            [SEARCH_PARAM_FILTERS_KEY]: JSON.stringify({ date_from: '-7d' }),
        })
        const viewerDashboard = { ...MOCK_DASHBOARD, user_access_level: AccessControlLevel.Viewer }
        const logic = dashboardLogic({ id: viewerDashboard.id, dashboard: viewerDashboard })
        logic.mount()

        render(
            <BindLogic logic={dashboardLogic} props={{ id: viewerDashboard.id, dashboard: viewerDashboard }}>
                <DashboardFilterBar />
            </BindLogic>
        )

        expect(document.querySelector('[data-attr="dashboard-temporary-filters"]')).toBeInTheDocument()
        expect(document.querySelector('[data-attr="dashboard-save-filters"]')).not.toBeInTheDocument()

        logic.unmount()
    })
})

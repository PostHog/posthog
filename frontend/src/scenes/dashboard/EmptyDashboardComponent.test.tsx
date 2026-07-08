import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BindLogic } from 'kea'
import { router } from 'kea-router'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel, DashboardType, QueryBasedInsightModel } from '~/types'

import { dashboardLogic } from './dashboardLogic'
import { EmptyDashboardComponent } from './EmptyDashboardComponent'

jest.mock('./emptyDashboardAiStarterPrompts', () => ({
    EmptyDashboardAiStarterPrompts: () => null,
}))

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

describe('EmptyDashboardComponent', () => {
    beforeEach(() => {
        localStorage.clear()
        sessionStorage.clear()
        useMocks({
            post: {
                '/api/environments/:team_id/query/': () => [200, { results: [] }],
            },
        })
        initKeaTests()
        featureFlagLogic.mount()
        maxGlobalLogic.mount()
    })

    afterEach(() => {
        cleanup()
    })

    function renderEmptyState(opts: { widgetsEnabled?: boolean } = {}): {
        logic: ReturnType<typeof dashboardLogic.build>
    } {
        const { widgetsEnabled = false } = opts

        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.DASHBOARD_WIDGETS], {
            [FEATURE_FLAGS.DASHBOARD_WIDGETS]: widgetsEnabled,
        })

        const logic = dashboardLogic({ id: MOCK_DASHBOARD.id, dashboard: MOCK_DASHBOARD })
        logic.mount()

        render(
            <BindLogic logic={dashboardLogic} props={{ id: MOCK_DASHBOARD.id, dashboard: MOCK_DASHBOARD }}>
                <EmptyDashboardComponent loading={false} canEdit={true} />
            </BindLogic>
        )

        return { logic }
    }

    async function openGetStartedDropdown(): Promise<void> {
        await userEvent.click(document.querySelector('[data-attr="dashboard-add-dropdown"]')!)
    }

    it('routes Add widget preview to feature previews when flag is disabled', async () => {
        const pushSpy = jest.spyOn(router.actions, 'push')
        const { logic } = renderEmptyState()

        await openGetStartedDropdown()
        await userEvent.click(screen.getByText('Add widget'))

        expect(pushSpy).toHaveBeenCalledWith(urls.featurePreview(FEATURE_FLAGS.DASHBOARD_WIDGETS))
        expect(logic.values.addWidgetModalOpen).toBe(false)

        pushSpy.mockRestore()
        logic.unmount()
    })

    it('shows Add text card in Get started dropdown', async () => {
        const { logic } = renderEmptyState()

        await openGetStartedDropdown()

        expect(screen.getByText('Add text card')).toBeInTheDocument()
        expect(screen.getByText('Add widget')).toBeInTheDocument()
        expect(screen.getByText('BETA')).toBeInTheDocument()

        logic.unmount()
    })

    it('shows Add widget in Get started dropdown when dashboard widgets flag is enabled', async () => {
        const { logic } = renderEmptyState({ widgetsEnabled: true })

        await openGetStartedDropdown()

        expect(screen.getByText('Add widget')).toBeInTheDocument()
        expect(screen.getByText('NEW')).toBeInTheDocument()

        logic.unmount()
    })

    it('opens add widget modal when Add widget is clicked', async () => {
        const { logic } = renderEmptyState({ widgetsEnabled: true })

        await openGetStartedDropdown()
        await userEvent.click(screen.getByText('Add widget'))

        expect(logic.values.addWidgetModalOpen).toBe(true)

        logic.unmount()
    })
})

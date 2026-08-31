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

import { addInsightToDashboardLogic } from './addInsightToDashboardModalLogic'
import { dashboardLogic } from './dashboardLogic'
import { EmptyDashboardComponent } from './EmptyDashboardComponent'

jest.mock('./emptyDashboardAiStarterPrompts', () => ({
    EmptyDashboardAiStarterPrompts: () => <div>Create a chart from a question</div>,
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

    function renderEmptyState(opts: { widgetsEnabled?: boolean; canEdit?: boolean } = {}): {
        logic: ReturnType<typeof dashboardLogic.build>
    } {
        const { widgetsEnabled = false, canEdit = true } = opts

        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.DASHBOARD_WIDGETS], {
            [FEATURE_FLAGS.DASHBOARD_WIDGETS]: widgetsEnabled,
        })

        const logic = dashboardLogic({ id: MOCK_DASHBOARD.id, dashboard: MOCK_DASHBOARD })
        logic.mount()

        render(
            <BindLogic logic={dashboardLogic} props={{ id: MOCK_DASHBOARD.id, dashboard: MOCK_DASHBOARD }}>
                <EmptyDashboardComponent loading={false} canEdit={canEdit} />
            </BindLogic>
        )

        return { logic }
    }

    async function openAddFirstChartDropdown(): Promise<void> {
        await userEvent.click(document.querySelector('[data-attr="dashboard-add-dropdown"]')!)
    }

    it('reserves space for dashboard controls while loading', () => {
        render(<EmptyDashboardComponent loading canEdit />)

        expect(document.querySelector('[data-attr="dashboard-loading-controls"]')).toBeInTheDocument()
    })

    it('shows clear paths to add an existing chart or create one with PostHog AI', () => {
        const { logic } = renderEmptyState()

        expect(screen.getByText('Build your dashboard')).toBeInTheDocument()
        expect(
            screen.getByText(
                'Add a chart from your library, or start with a question about what matters to your product.'
            )
        ).toBeInTheDocument()
        expect(screen.getByText('Add an existing chart')).toBeInTheDocument()
        expect(screen.getByText('or View Web Analytics')).toBeInTheDocument()
        expect(screen.getByText('Create a chart from a question')).toBeInTheDocument()

        logic.unmount()
    })

    it('opens the insight picker when Add your first chart is clicked', async () => {
        const { logic } = renderEmptyState()

        await userEvent.click(document.querySelector('[data-attr="dashboard-add-graph-header"]')!)

        expect(addInsightToDashboardLogic.values.addInsightToDashboardModalVisible).toBe(true)

        logic.unmount()
    })

    it('disables the dropdown when the user cannot edit the dashboard', () => {
        const { logic } = renderEmptyState({ canEdit: false })

        expect(document.querySelector('[data-attr="dashboard-add-dropdown"]')).toHaveAttribute('aria-disabled', 'true')

        logic.unmount()
    })

    it('routes Widget preview to feature previews when flag is disabled', async () => {
        const pushSpy = jest.spyOn(router.actions, 'push')
        const { logic } = renderEmptyState()

        await openAddFirstChartDropdown()
        await userEvent.click(screen.getByText('Widget'))

        expect(pushSpy).toHaveBeenCalledWith(urls.featurePreview(FEATURE_FLAGS.DASHBOARD_WIDGETS))
        expect(logic.values.addWidgetModalOpen).toBe(false)

        pushSpy.mockRestore()
        logic.unmount()
    })

    it('shows the shared dashboard add options in the Add your first chart dropdown', async () => {
        const { logic } = renderEmptyState()

        await openAddFirstChartDropdown()

        expect(screen.getByText('Content')).toBeInTheDocument()
        expect(screen.getByText('Charts')).toBeInTheDocument()
        expect(screen.getByText('Add text')).toBeInTheDocument()
        expect(screen.getByText('Button')).toBeInTheDocument()
        expect(screen.getByText('Widget')).toBeInTheDocument()
        expect(screen.getByText('BETA')).toBeInTheDocument()

        logic.unmount()
    })

    it('shows Widget in the Add your first chart dropdown when dashboard widgets flag is enabled', async () => {
        const { logic } = renderEmptyState({ widgetsEnabled: true })

        await openAddFirstChartDropdown()

        expect(screen.getByText('Widget')).toBeInTheDocument()
        expect(screen.getByText('NEW')).toBeInTheDocument()

        logic.unmount()
    })

    it('opens the add widget modal when Widget is clicked', async () => {
        const { logic } = renderEmptyState({ widgetsEnabled: true })

        await openAddFirstChartDropdown()
        await userEvent.click(screen.getByText('Widget'))

        expect(logic.values.addWidgetModalOpen).toBe(true)

        logic.unmount()
    })
})

import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BindLogic } from 'kea'

import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel, DashboardType } from '~/types'

import { addInsightToDashboardLogic } from './addInsightToDashboardModalLogic'
import { dashboardLogic } from './dashboardLogic'
import { EmptyDashboardComponent } from './EmptyDashboardComponent'

const MOCK_DASHBOARD: DashboardType = {
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
        maxGlobalLogic.mount()
    })

    afterEach(() => {
        cleanup()
    })

    function renderEmptyState(opts: { canEdit?: boolean } = {}): {
        logic: ReturnType<typeof dashboardLogic.build>
    } {
        const { canEdit = true } = opts

        const logic = dashboardLogic({ id: MOCK_DASHBOARD.id, dashboard: MOCK_DASHBOARD })
        logic.mount()

        render(
            <BindLogic logic={dashboardLogic} props={{ id: MOCK_DASHBOARD.id, dashboard: MOCK_DASHBOARD }}>
                <EmptyDashboardComponent loading={false} canEdit={canEdit} />
            </BindLogic>
        )

        return { logic }
    }

    async function openBuildItMyselfMenu(): Promise<void> {
        await userEvent.click(document.querySelector('[data-attr="dashboard-add-dropdown"]')!)
    }

    it('reserves space for dashboard controls while loading', () => {
        render(<EmptyDashboardComponent loading canEdit />)

        expect(document.querySelector('[data-attr="dashboard-loading-controls"]')).toBeInTheDocument()
    })

    it('shows clear paths to add a chart or create one with PostHog AI', () => {
        const { logic } = renderEmptyState()

        expect(screen.getByText('Build your dashboard')).toBeInTheDocument()
        expect(
            screen.getByText(
                'Add a chart from your library, or start with a question about what matters to your product.'
            )
        ).toBeInTheDocument()
        expect(screen.getByText('Add a chart')).toBeInTheDocument()
        expect(screen.getByText('Build it myself')).toBeInTheDocument()
        expect(screen.getByText('or View Web Analytics')).toBeInTheDocument()
        expect(screen.getByText('What do you want to learn?')).toBeInTheDocument()

        logic.unmount()
    })

    it('opens the insight picker when Add a chart is clicked', async () => {
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

    it('shows the shared dashboard add options in the Build it myself menu', async () => {
        const { logic } = renderEmptyState()

        await openBuildItMyselfMenu()

        expect(screen.getByText('Content')).toBeInTheDocument()
        expect(screen.getByText('Charts')).toBeInTheDocument()
        expect(screen.getByText('Add text')).toBeInTheDocument()
        expect(screen.getByText('Image')).toBeInTheDocument()
        expect(screen.getByText('Button')).toBeInTheDocument()
        expect(screen.getByText('Widget')).toBeInTheDocument()
        expect(screen.queryByText('BETA')).not.toBeInTheDocument()
        expect(screen.getAllByText('NEW')).toHaveLength(2)

        logic.unmount()
    })

    it('opens the add widget modal when Widget is clicked', async () => {
        const { logic } = renderEmptyState()

        await openBuildItMyselfMenu()
        await userEvent.click(screen.getByText('Widget'))

        expect(logic.values.addWidgetModalOpen).toBe(true)

        logic.unmount()
    })
})

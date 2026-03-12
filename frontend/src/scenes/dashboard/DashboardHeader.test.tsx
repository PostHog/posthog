import '@testing-library/jest-dom'

import { cleanup, render } from '@testing-library/react'
import { BindLogic } from 'kea'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel, DashboardMode, DashboardType, QueryBasedInsightModel } from '~/types'

import { DashboardHeader } from './DashboardHeader'
import { dashboardLogic } from './dashboardLogic'

jest.mock('lib/components/FullScreen', () => ({
    FullScreen: () => null,
}))
jest.mock('scenes/max/MaxTool', () => ({
    MaxTool: ({ children }: any) => <>{children}</>,
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

function makeDashboard(overrides: Record<string, any> = {}): DashboardType<QueryBasedInsightModel> {
    return { ...MOCK_DASHBOARD, ...overrides }
}

beforeAll(() => {
    const root = document.createElement('div')
    root.id = 'root'
    document.body.appendChild(root)
})

describe('DashboardHeader', () => {
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
    })

    afterEach(() => {
        cleanup()
    })

    function renderHeader(opts: {
        dashboard?: DashboardType<QueryBasedInsightModel>
        dashboardMode?: DashboardMode | null
    }): { logic: ReturnType<typeof dashboardLogic.build> } {
        const { dashboard = MOCK_DASHBOARD, dashboardMode = null } = opts

        const logic = dashboardLogic({ id: dashboard.id, dashboard })
        logic.mount()

        if (dashboardMode) {
            logic.actions.setDashboardMode(dashboardMode, null)
        }

        render(
            <BindLogic logic={dashboardLogic} props={{ id: dashboard.id, dashboard }}>
                <DashboardHeader />
            </BindLogic>
        )

        return { logic }
    }

    it.each([
        {
            scenario: 'View mode, can edit',
            dashboardMode: null as DashboardMode | null,
            canEdit: true,
            visible: ['dashboard-share-button', 'add-text-tile-to-dashboard', 'dashboard-add-graph-header'],
            notVisible: ['dashboard-edit-mode-discard', 'dashboard-edit-mode-save'],
        },
        {
            scenario: 'View mode, cannot edit',
            dashboardMode: null as DashboardMode | null,
            canEdit: false,
            visible: ['dashboard-share-button', 'add-text-tile-to-dashboard', 'dashboard-add-graph-header'],
            notVisible: ['dashboard-edit-mode-discard', 'dashboard-edit-mode-save'],
        },
        {
            scenario: 'Edit mode',
            dashboardMode: DashboardMode.Edit,
            canEdit: true,
            visible: ['dashboard-edit-mode-discard', 'dashboard-edit-mode-save'],
            notVisible: ['dashboard-share-button', 'add-text-tile-to-dashboard', 'dashboard-add-graph-header'],
        },
        {
            scenario: 'Fullscreen mode',
            dashboardMode: DashboardMode.Fullscreen,
            canEdit: true,
            visible: ['dashboard-exit-presentation-mode'],
            notVisible: ['dashboard-share-button', 'dashboard-edit-mode-save'],
        },
    ])('$scenario shows correct action buttons', ({ dashboardMode, canEdit, visible, notVisible }) => {
        const dashboard = makeDashboard({
            user_access_level: canEdit ? AccessControlLevel.Editor : AccessControlLevel.Viewer,
        })
        const { logic } = renderHeader({ dashboard, dashboardMode })

        for (const attr of visible) {
            expect(document.querySelector(`[data-attr="${attr}"]`)).toBeInTheDocument()
        }
        for (const attr of notVisible) {
            expect(document.querySelector(`[data-attr="${attr}"]`)).not.toBeInTheDocument()
        }

        logic.unmount()
    })

    it('new dashboard gets forceEdit on SceneTitleSection', () => {
        const dashboard = makeDashboard({
            name: 'New Dashboard',
            tiles: [
                {
                    id: 1,
                    layouts: {},
                    color: null,
                    insight: {
                        id: 10,
                        short_id: 'xyz',
                        name: 'Some insight',
                        query: { kind: 'TrendsQuery', series: [] },
                    },
                },
            ],
        })
        const { logic } = renderHeader({ dashboard })

        const textarea = document.querySelector('[data-attr="scene-title-textarea"]')
        expect(textarea).toBeInTheDocument()

        logic.unmount()
    })

    it('existing dashboard does not get forceEdit on SceneTitleSection', () => {
        const dashboard = makeDashboard({
            name: 'My Custom Dashboard',
            created_at: '2020-01-01T00:00:00Z',
            tiles: [
                {
                    id: 1,
                    layouts: {},
                    color: null,
                    insight: {
                        id: 10,
                        short_id: 'xyz',
                        name: 'Some insight',
                        query: { kind: 'TrendsQuery', series: [] },
                    },
                },
            ],
        })
        const { logic } = renderHeader({ dashboard })

        const textarea = document.querySelector('[data-attr="scene-title-textarea"]')
        // SceneTitleSection should not be in forceEdit for old dashboards —
        // it renders but the textarea won't be auto-focused/editable
        expect(textarea).not.toBeInTheDocument()

        logic.unmount()
    })
})

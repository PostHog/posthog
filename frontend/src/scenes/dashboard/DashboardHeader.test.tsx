import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { BindLogic } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { DashboardEventSource } from 'lib/utils/eventUsageLogic'

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
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.DASHBOARD_CUSTOMIZATION], {
            [FEATURE_FLAGS.DASHBOARD_CUSTOMIZATION]: true,
        })
    })

    afterEach(() => {
        cleanup()
    })

    function renderHeader(opts: {
        dashboard?: DashboardType<QueryBasedInsightModel> | null
        dashboardMode?: DashboardMode | null
        dashboardModeSource?: DashboardEventSource
        loading?: boolean
    }): { logic: ReturnType<typeof dashboardLogic.build> } {
        const {
            dashboard = MOCK_DASHBOARD,
            dashboardMode = null,
            dashboardModeSource = DashboardEventSource.Browser,
            loading = false,
        } = opts

        const logic = dashboardLogic({ id: dashboard?.id ?? MOCK_DASHBOARD.id, dashboard: dashboard ?? undefined })
        logic.mount()
        if (dashboardMode) {
            logic.actions.setDashboardMode(dashboardMode, dashboardModeSource)
        }

        render(
            <BindLogic
                logic={dashboardLogic}
                props={{ id: dashboard?.id ?? MOCK_DASHBOARD.id, dashboard: dashboard ?? undefined }}
            >
                <DashboardHeader loading={loading} />
            </BindLogic>
        )

        return { logic }
    }

    it('keeps the scene header visible while the dashboard is loading', () => {
        const { logic } = renderHeader({ dashboard: null, loading: true })

        expect(document.querySelector('.scene-title-section')).toBeInTheDocument()

        logic.unmount()
    })

    it('keeps the dashboard name and description visible during a background load', () => {
        const { logic } = renderHeader({ dashboard: MOCK_DASHBOARD, loading: true })

        expect(screen.getByText('Test Dashboard')).toBeInTheDocument()
        expect(screen.getByText('A test dashboard')).toBeInTheDocument()

        logic.unmount()
    })

    it.each([
        {
            scenario: 'View mode, can edit',
            dashboardMode: null as DashboardMode | null,
            canEdit: true,
            visible: [],
            notVisible: [
                'dashboard-add-tile',
                'dashboard-share-button',
                'dashboard-edit-mode-button',
                'dashboard-edit-mode-discard',
                'dashboard-edit-mode-save',
            ],
        },
        {
            scenario: 'View mode, cannot edit',
            dashboardMode: null as DashboardMode | null,
            canEdit: false,
            visible: [],
            notVisible: [
                'dashboard-add-tile',
                'dashboard-share-button',
                'dashboard-edit-mode-discard',
                'dashboard-edit-mode-save',
                'dashboard-edit-mode-button',
            ],
        },
        {
            scenario: 'Filter edit mode',
            dashboardMode: DashboardMode.Edit,
            dashboardModeSource: DashboardEventSource.DashboardFilters,
            canEdit: true,
            visible: [],
            notVisible: [
                'dashboard-add-tile',
                'dashboard-edit-mode-discard',
                'dashboard-edit-mode-save',
                'dashboard-share-button',
                'dashboard-edit-layout-customize-dropdown',
                'add-text-tile-to-dashboard',
                'dashboard-add-graph-header',
            ],
        },
        {
            scenario: 'Layout edit mode',
            dashboardMode: DashboardMode.Edit,
            dashboardModeSource: DashboardEventSource.SceneCommonButtons,
            canEdit: true,
            visible: ['dashboard-edit-mode-discard', 'dashboard-edit-mode-save'],
            notVisible: [
                'dashboard-add-tile',
                'dashboard-share-button',
                'dashboard-edit-layout-customize-dropdown',
                'add-text-tile-to-dashboard',
                'dashboard-add-graph-header',
            ],
        },
        {
            scenario: 'Fullscreen mode',
            dashboardMode: DashboardMode.Fullscreen,
            canEdit: true,
            visible: ['dashboard-exit-presentation-mode'],
            notVisible: ['dashboard-share-button', 'dashboard-edit-mode-save'],
        },
    ])(
        '$scenario shows correct action buttons',
        ({ dashboardMode, dashboardModeSource, canEdit, visible, notVisible }) => {
            const dashboard = makeDashboard({
                user_access_level: canEdit ? AccessControlLevel.Editor : AccessControlLevel.Viewer,
            })
            const { logic } = renderHeader({ dashboard, dashboardMode, dashboardModeSource })

            for (const attr of visible) {
                expect(document.querySelector(`[data-attr="${attr}"]`)).toBeInTheDocument()
            }
            for (const attr of notVisible) {
                expect(document.querySelector(`[data-attr="${attr}"]`)).not.toBeInTheDocument()
            }

            logic.unmount()
        }
    )
})

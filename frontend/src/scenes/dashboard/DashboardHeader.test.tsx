import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { BindLogic } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { DashboardEventSource } from 'lib/utils/eventUsageLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel, DashboardMode, DashboardType, QueryBasedInsightModel } from '~/types'

import { useMcpToolApplyBack } from 'products/posthog_ai/frontend/api/logics'
import type { ToolStreamEvent } from 'products/posthog_ai/frontend/types/streamTypes'

import { DashboardHeader, insightIsAddedToDashboard } from './DashboardHeader'
import { DashboardLoadAction, dashboardLogic } from './dashboardLogic'

jest.mock('lib/components/FullScreen', () => ({
    FullScreen: () => null,
}))
jest.mock('scenes/max/MaxTool', () => ({
    MaxTool: ({ children }: any) => <>{children}</>,
}))

jest.mock('products/posthog_ai/frontend/api/logics', () => ({
    useMcpToolApplyBack: jest.fn(),
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
        spyOnLoadDashboard?: boolean
    }): { logic: ReturnType<typeof dashboardLogic.build>; loadDashboard?: jest.SpyInstance } {
        const {
            dashboard = MOCK_DASHBOARD,
            dashboardMode = null,
            dashboardModeSource = DashboardEventSource.Browser,
            loading = false,
        } = opts

        const logic = dashboardLogic({ id: dashboard?.id ?? MOCK_DASHBOARD.id, dashboard: dashboard ?? undefined })
        logic.mount()
        const loadDashboard = opts.spyOnLoadDashboard
            ? jest.spyOn(logic.actions, 'loadDashboard').mockImplementation()
            : undefined

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

        return { logic, loadDashboard }
    }

    it('keeps the scene header visible while the dashboard is loading', () => {
        const { logic } = renderHeader({ dashboard: null, loading: true })

        expect(document.querySelector('.scene-title-section')).toBeInTheDocument()

        logic.unmount()
    })

    it('recognizes sandbox insight calls that add to the open dashboard', () => {
        expect(insightIsAddedToDashboard({ dashboards: ['5', 8] }, 5)).toBe(true)
        expect(insightIsAddedToDashboard({ dashboards: [8] }, 5)).toBe(false)
        expect(insightIsAddedToDashboard({ dashboards: '5' }, 5)).toBe(false)
    })

    it('reloads the open dashboard when sandbox AI adds an insight to it', () => {
        const { logic, loadDashboard } = renderHeader({ dashboard: MOCK_DASHBOARD, spyOnLoadDashboard: true })
        const applyBackOptions = jest
            .mocked(useMcpToolApplyBack)
            .mock.calls.map(([options]) => options)
            .find((options) => options.targetKey === `dashboard:${MOCK_DASHBOARD.id}`)

        applyBackOptions?.onApply({} as ToolStreamEvent, { innerInput: { dashboards: [MOCK_DASHBOARD.id] } })

        expect(loadDashboard).toHaveBeenCalledWith({ action: DashboardLoadAction.Update })
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
            visible: ['dashboard-share-button', 'dashboard-add-tile', 'dashboard-edit-mode-button'],
            notVisible: ['dashboard-edit-mode-discard', 'dashboard-edit-mode-save'],
        },
        {
            scenario: 'View mode, cannot edit',
            dashboardMode: null as DashboardMode | null,
            canEdit: false,
            visible: ['dashboard-share-button', 'dashboard-add-tile'],
            notVisible: ['dashboard-edit-mode-discard', 'dashboard-edit-mode-save', 'dashboard-edit-mode-button'],
        },
        {
            scenario: 'Filter edit mode',
            dashboardMode: DashboardMode.Edit,
            dashboardModeSource: DashboardEventSource.DashboardFilters,
            canEdit: true,
            visible: ['dashboard-add-tile', 'dashboard-edit-layout-customize-dropdown'],
            notVisible: [
                'dashboard-edit-mode-discard',
                'dashboard-edit-mode-save',
                'dashboard-share-button',
                'add-text-tile-to-dashboard',
                'dashboard-add-graph-header',
            ],
        },
        {
            scenario: 'Layout edit mode',
            dashboardMode: DashboardMode.Edit,
            dashboardModeSource: DashboardEventSource.SceneCommonButtons,
            canEdit: true,
            visible: [
                'dashboard-edit-mode-discard',
                'dashboard-edit-mode-save',
                'dashboard-edit-layout-customize-dropdown',
                'dashboard-add-tile',
            ],
            notVisible: ['dashboard-share-button', 'add-text-tile-to-dashboard', 'dashboard-add-graph-header'],
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

import { act, cleanup, render, waitFor } from '@testing-library/react'
import { BindLogic } from 'kea'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel, DashboardPlacement } from '~/types'

import { useMcpToolApplyBack } from 'products/posthog_ai/frontend/api/logics'
import type { ToolStreamEvent } from 'products/posthog_ai/frontend/types/streamTypes'

import { maxMocks } from '../max/testUtils'
import { Dashboard } from './Dashboard'
import { DashboardAiSync } from './DashboardAiSync'
import { DASHBOARD_AI_MUTATION_TOOLS, dashboardAiSyncLogic } from './dashboardAiSyncLogic'
import { dashboardLogic } from './dashboardLogic'
import { dashboardResult } from './dashboardLogic.testHelpers'

jest.mock('products/posthog_ai/frontend/api/logics', () => ({
    useAttachedContext: jest.fn(),
    useMcpToolApplyBack: jest.fn(),
    useWelcomeOverride: jest.fn(),
}))

describe('DashboardAiSync', () => {
    beforeEach(() => {
        localStorage.clear()
        useMocks(maxMocks)
        initKeaTests()
        featureFlagLogic.actions.setFeatureFlags(
            [FEATURE_FLAGS.PHAI_SCENE_AUTO_OPEN, FEATURE_FLAGS.PHAI_SANDBOX_MODE],
            {
                [FEATURE_FLAGS.PHAI_SCENE_AUTO_OPEN]: true,
                [FEATURE_FLAGS.PHAI_SANDBOX_MODE]: true,
            }
        )
    })

    afterEach(() => {
        cleanup()
        jest.clearAllMocks()
    })

    const setFlags = (flags: string[]): void => {
        featureFlagLogic.actions.setFeatureFlags(flags, Object.fromEntries(flags.map((flag) => [flag, true])))
    }

    const allFlags = [FEATURE_FLAGS.PHAI_SCENE_AUTO_OPEN, FEATURE_FLAGS.PHAI_SANDBOX_MODE]
    const editableDashboard = (): ReturnType<typeof dashboardResult> => ({
        ...dashboardResult(7, []),
        user_access_level: AccessControlLevel.Editor,
    })
    const editableDashboardWithTile = (): ReturnType<typeof dashboardResult> => ({
        ...editableDashboard(),
        tiles: [
            {
                id: 41,
                layouts: {},
                color: null,
                text: { id: 91, body: 'Dashboard status', last_modified_at: '2026-01-01T00:00:00Z' },
            },
        ],
    })

    it('registers the exact dashboard mutation tools for completed calls', () => {
        render(<DashboardAiSync dashboardId={7} />)

        expect(useMcpToolApplyBack).toHaveBeenCalledWith({
            tools: DASHBOARD_AI_MUTATION_TOOLS,
            targetKey: 'dashboard:7',
            applyOn: 'tool_call_completed',
            active: true,
            onApply: expect.any(Function),
        })
    })

    it('forwards the completed event and resolved inner input to the dashboard sync logic', () => {
        const dashboard = dashboardResult(7, [])
        const dashboardSceneLogic = dashboardLogic({ id: 7, dashboard })
        const syncLogic = dashboardAiSyncLogic({ dashboardId: 7 })
        dashboardSceneLogic.mount()
        syncLogic.mount()
        const applyToolCompletion = jest.spyOn(syncLogic.actions, 'applyToolCompletion')

        render(<DashboardAiSync dashboardId={7} />)

        const options = jest.mocked(useMcpToolApplyBack).mock.calls[0][0]
        const event = { toolName: 'dashboard-update' } as ToolStreamEvent
        const innerInput = { id: 7 }
        options.onApply(event, { innerInput })

        expect(applyToolCompletion).toHaveBeenCalledWith(event, innerInput)
        syncLogic.unmount()
        dashboardSceneLogic.unmount()
    })

    it.each([
        {
            name: 'the scene rollout flag is off',
            flags: [FEATURE_FLAGS.PHAI_SANDBOX_MODE],
            view: 'new' as const,
            preflight: { cloud: true },
            expected: false,
        },
        {
            name: 'the legacy runtime is selected',
            flags: allFlags,
            view: 'legacy' as const,
            preflight: { cloud: true },
            expected: false,
        },
        {
            name: 'PostHog AI is unavailable',
            flags: allFlags,
            view: 'new' as const,
            preflight: { cloud: false, is_debug: false, anthropic_available: false },
            expected: false,
        },
        {
            name: 'the sandbox runtime and all gates are enabled',
            flags: allFlags,
            view: 'new' as const,
            preflight: { cloud: true },
            expected: true,
        },
    ])('mounts the apply-back owner=$expected when $name', ({ flags, view, preflight, expected }) => {
        const maxLogic = maxGlobalLogic()
        maxLogic.mount()
        setFlags(flags)
        maxLogic.actions.setPhaiViewMode(view)
        preflightLogic.actions.loadPreflightSuccess(preflight as any)
        const dashboard = editableDashboardWithTile()

        render(<Dashboard id="7" dashboard={dashboard} placement={DashboardPlacement.Dashboard} />)

        expect(useMcpToolApplyBack).toHaveBeenCalledTimes(expected ? 1 : 0)
        expect(dashboardAiSyncLogic({ dashboardId: 7 }).isMounted()).toBe(expected)
        maxLogic.unmount()
    })

    it('mounts exactly one bridge for a loaded editable standard dashboard', () => {
        const dashboard = editableDashboard()

        render(<Dashboard id="7" dashboard={dashboard} placement={DashboardPlacement.Dashboard} />)

        expect(useMcpToolApplyBack).toHaveBeenCalledTimes(1)
        expect(useMcpToolApplyBack).toHaveBeenCalledWith(
            expect.objectContaining({ tools: DASHBOARD_AI_MUTATION_TOOLS, targetKey: 'dashboard:7' })
        )
    })

    it.each([
        { name: 'public placement', placement: DashboardPlacement.Public },
        { name: 'export placement', placement: DashboardPlacement.Export },
        { name: 'project homepage placement', placement: DashboardPlacement.ProjectHomepage },
    ])('does not mount the bridge for $name', ({ placement }) => {
        const dashboard = editableDashboardWithTile()

        render(<Dashboard id="7" dashboard={dashboard} placement={placement} />)

        expect(useMcpToolApplyBack).not.toHaveBeenCalled()
        expect(dashboardAiSyncLogic({ dashboardId: 7 }).isMounted()).toBe(false)
    })

    it('does not mount the bridge for a read-only dashboard', () => {
        const dashboard = { ...editableDashboardWithTile(), user_access_level: AccessControlLevel.Viewer }

        render(<Dashboard id="7" dashboard={dashboard} placement={DashboardPlacement.Dashboard} />)

        expect(useMcpToolApplyBack).not.toHaveBeenCalled()
        expect(dashboardAiSyncLogic({ dashboardId: 7 }).isMounted()).toBe(false)
    })

    it('disposes pending synchronization without telemetry when the scene gate turns off', async () => {
        const dashboard = editableDashboardWithTile()
        const sceneLogic = dashboardLogic({ id: 7, dashboard, placement: DashboardPlacement.Dashboard })
        let resolveDashboardReload!: () => void
        const pendingReload = new Promise<void>((resolve) => {
            resolveDashboardReload = resolve
        })
        const loadDashboard = jest.spyOn(sceneLogic.asyncActions, 'loadDashboard').mockReturnValue(pendingReload)
        jest.mocked(posthog.capture).mockClear()
        const maxLogic = maxGlobalLogic()
        maxLogic.mount()
        maxLogic.actions.setPhaiViewMode('new')
        const { rerender } = render(<Dashboard id="7" dashboard={dashboard} placement={DashboardPlacement.Dashboard} />)
        const syncLogic = dashboardAiSyncLogic({ dashboardId: 7 })

        act(() =>
            syncLogic.actions.queueDashboardSync({
                family: 'dashboard',
                dashboardId: 7,
                tileIds: [],
                insightIds: [],
                deletesDashboard: false,
            })
        )
        expect(loadDashboard).toHaveBeenCalledTimes(1)

        act(() => setFlags([FEATURE_FLAGS.PHAI_SANDBOX_MODE]))
        rerender(<Dashboard id="7" dashboard={dashboard} placement={DashboardPlacement.Dashboard} />)
        resolveDashboardReload()
        await pendingReload
        await Promise.resolve()
        await Promise.resolve()

        await waitFor(() => expect(dashboardAiSyncLogic({ dashboardId: 7 }).isMounted()).toBe(false))
        expect(posthog.capture).not.toHaveBeenCalledWith('dashboard ai sync completed', expect.anything())
        loadDashboard.mockRestore()
        maxLogic.unmount()
    })

    it('does not mount the bridge before the dashboard loads', () => {
        render(<Dashboard id="7" placement={DashboardPlacement.Dashboard} />)

        expect(useMcpToolApplyBack).not.toHaveBeenCalled()
    })

    it.each([
        {
            name: 'access is denied',
            setup: (logic: ReturnType<typeof dashboardLogic.build>) => logic.actions.setAccessDeniedToDashboard(),
        },
        {
            name: 'loading has failed',
            setup: (logic: ReturnType<typeof dashboardLogic.build>) => logic.actions.setDashboardFailedToLoad(),
        },
    ])('does not mount the bridge when $name', ({ setup }) => {
        const dashboard = editableDashboard()
        const logic = dashboardLogic({ id: 7, dashboard, placement: DashboardPlacement.Dashboard })
        logic.mount()
        setup(logic)

        render(
            <BindLogic logic={dashboardLogic} props={{ id: 7, dashboard, placement: DashboardPlacement.Dashboard }}>
                <Dashboard id="7" dashboard={dashboard} placement={DashboardPlacement.Dashboard} />
            </BindLogic>
        )

        expect(useMcpToolApplyBack).not.toHaveBeenCalled()
        logic.unmount()
    })
})

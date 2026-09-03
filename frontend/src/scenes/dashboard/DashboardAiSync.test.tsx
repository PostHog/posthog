import '@testing-library/jest-dom'

import { cleanup, render } from '@testing-library/react'
import { BindLogic } from 'kea'

import { initKeaTests } from '~/test/init'
import { DashboardPlacement, DashboardTile, QueryBasedInsightModel } from '~/types'

import { useAttachedContext, useMcpToolApplyBack } from 'products/posthog_ai/frontend/api/logics'

import { Dashboard } from './Dashboard'
import { DashboardAiSync } from './DashboardAiSync'
import { DASHBOARD_AI_TOOL_NAMES, dashboardAiSyncLogic } from './dashboardAiSyncLogic'
import { dashboardLogic } from './dashboardLogic'
import { dashboardResult } from './dashboardLogic.testHelpers'

jest.mock('products/posthog_ai/frontend/api/logics', () => ({
    useAttachedContext: jest.fn(),
    useMcpToolApplyBack: jest.fn(),
}))

jest.mock('./EmptyDashboardComponent', () => ({
    EmptyDashboardComponent: () => null,
}))

describe('DashboardAiSync', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
        jest.clearAllMocks()
    })

    it('applies completed dashboard tool calls to the current dashboard snapshot', () => {
        const tiles: DashboardTile<QueryBasedInsightModel>[] = [
            {
                id: 10,
                layouts: {},
                color: null,
                insight: { id: 42, short_id: 'insight-42' } as QueryBasedInsightModel,
            },
        ]
        const dashboard = dashboardResult(5, tiles)
        const dashboardSceneLogic = dashboardLogic({ id: 5, dashboard })
        const syncLogic = dashboardAiSyncLogic({ dashboardId: 5 })
        const agentToolCompleted = jest.spyOn(syncLogic.actions, 'agentToolCompleted')
        dashboardSceneLogic.mount()
        syncLogic.mount()

        render(
            <BindLogic logic={dashboardLogic} props={{ id: 5, dashboard }}>
                <DashboardAiSync dashboardId={5} />
            </BindLogic>
        )

        const applyBackOptions = jest.mocked(useMcpToolApplyBack).mock.calls[0][0]
        expect(applyBackOptions).toMatchObject({
            tools: DASHBOARD_AI_TOOL_NAMES,
            targetKey: 'dashboard:5',
            active: true,
            applyOn: 'tool_call_completed',
        })

        applyBackOptions.onApply({ toolName: 'dashboard-create-tile' } as never, { innerInput: { id: 5 } })

        expect(agentToolCompleted).toHaveBeenCalledWith('dashboard-create-tile', { id: 5 }, [
            { tileId: 10, insightId: 42, insightShortId: 'insight-42' },
        ])

        syncLogic.unmount()
        dashboardSceneLogic.unmount()
    })

    it('attaches the current dashboard and skill context for standard dashboards', () => {
        const dashboard = dashboardResult(5, [])

        render(<Dashboard id="5" dashboard={dashboard} placement={DashboardPlacement.Dashboard} />)

        expect(useAttachedContext).toHaveBeenCalledWith(
            expect.arrayContaining([
                expect.objectContaining({ type: 'dashboard', key: 5 }),
                expect.objectContaining({ type: 'skill', key: 'building-a-dashboard' }),
            ])
        )
    })

    it.each([DashboardPlacement.Public, DashboardPlacement.Export])(
        'does not mount the apply-back bridge for %s dashboards',
        (placement) => {
            const dashboard = dashboardResult(5, [])

            render(<Dashboard id="5" dashboard={dashboard} placement={placement} />)

            expect(useMcpToolApplyBack).not.toHaveBeenCalled()
            expect(useAttachedContext).toHaveBeenCalledWith(null)
        }
    )
})

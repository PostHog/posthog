import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { sceneLogic } from 'scenes/sceneLogic'
import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { insightsModel } from '~/models/insightsModel'
import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { InsightLogicProps, InsightShortId } from '~/types'

import { insightLogic } from './insightLogic'
import { insightModalsLogic } from './insightModalsLogic'

const Insight42 = '42' as InsightShortId

const savedInsightProps: InsightLogicProps = {
    dashboardItemId: Insight42,
    cachedInsight: {
        id: 42,
        short_id: Insight42,
        result: ['result'],
        saved: true,
        query: { kind: NodeKind.InsightVizNode, source: { kind: NodeKind.TrendsQuery, series: [] } },
    } as any,
}

describe('insightModalsLogic', () => {
    let logic: ReturnType<typeof insightModalsLogic.build>

    beforeEach(async () => {
        useMocks({
            get: {
                '/api/environments/:team_id/insights/42': { id: 42, short_id: Insight42, result: ['result'] },
                '/api/environments/:team_id/insights/': { results: [], count: 0 },
            },
            patch: {
                '/api/environments/:team_id/insights/:id': async ({ request, params }) => {
                    const payload = (await request.json()) as Record<string, any>
                    return [200, { ...payload, id: params.id, short_id: Insight42 }]
                },
            },
        })
        initKeaTests(true, { ...MOCK_DEFAULT_TEAM })
        teamLogic.mount()
        sceneLogic.mount()
        insightsModel.mount()
        insightLogic(savedInsightProps).mount()
        logic = insightModalsLogic(savedInsightProps)
        logic.mount()
    })

    it('saves first, then opens the add-to-dashboard modal once the save succeeds', async () => {
        await expectLogic(logic, () => {
            logic.actions.saveAndAddToDashboard()
        })
            .toDispatchActions(['saveAndAddToDashboard', 'saveInsight'])
            .toMatchValues({ pendingAddToDashboardAfterSave: true })
            .toDispatchActions(['saveInsightSuccess', 'openAddToDashboardModal'])
            .toMatchValues({ pendingAddToDashboardAfterSave: false, isAddToDashboardModalOpen: true })
    })

    it('does not open the modal and clears the pending flag when the save fails', async () => {
        // Hold the save open so the pending flag stays set, then drive the failure signal directly — this exercises
        // insightModalsLogic's reaction without depending on insightLogic re-throwing on a real API error.
        useMocks({ patch: { '/api/environments/:team_id/insights/:id': () => new Promise(() => {}) } })

        await expectLogic(logic, () => {
            logic.actions.saveAndAddToDashboard()
        }).toMatchValues({ pendingAddToDashboardAfterSave: true })

        await expectLogic(logic, () => {
            insightLogic(savedInsightProps).actions.saveInsightFailure()
        })
            .toDispatchActions(['saveInsightFailure'])
            .toNotHaveDispatchedActions(['openAddToDashboardModal'])
            .toMatchValues({ pendingAddToDashboardAfterSave: false, isAddToDashboardModalOpen: false })
    })

    it('does not open the modal on a plain save with nothing pending', async () => {
        await expectLogic(logic, () => {
            insightLogic(savedInsightProps).actions.saveInsightSuccess()
        })
            .toDispatchActions(['saveInsightSuccess'])
            .toNotHaveDispatchedActions(['openAddToDashboardModal'])
            .toMatchValues({ pendingAddToDashboardAfterSave: false, isAddToDashboardModalOpen: false })
    })
})

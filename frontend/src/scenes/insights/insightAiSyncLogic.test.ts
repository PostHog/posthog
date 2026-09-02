import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { InsightLogicProps, InsightShortId, QueryBasedInsightModel } from '~/types'

import { insightAlertsLogic } from 'products/alerts/frontend/logic/insightAlertsLogic'
import { subscriptionsLogic } from 'products/subscriptions/frontend/components/Subscriptions/subscriptionsLogic'

import { urls } from '../urls'
import { insightAiSyncLogic } from './insightAiSyncLogic'
import { insightDataLogic } from './insightDataLogic'
import { insightLogic } from './insightLogic'

const insightLogicProps: InsightLogicProps = {
    dashboardItemId: 'abc123' as InsightShortId,
    cachedInsight: {
        id: 42,
        short_id: 'abc123',
        saved: true,
        name: 'Saved insight',
        query: {
            kind: NodeKind.InsightVizNode,
            source: {
                kind: NodeKind.TrendsQuery,
                series: [{ kind: NodeKind.EventsNode, event: '$pageview', math: 'total' }],
            },
        },
    } as unknown as QueryBasedInsightModel,
}

describe('insightAiSyncLogic', () => {
    let logic: ReturnType<typeof insightAiSyncLogic.build>
    let insightSceneLogic: ReturnType<typeof insightLogic.build>
    let insightData: ReturnType<typeof insightDataLogic.build>

    beforeEach(() => {
        initKeaTests()
        insightSceneLogic = insightLogic(insightLogicProps)
        insightData = insightDataLogic(insightLogicProps)
        logic = insightAiSyncLogic({ insightLogicProps })
        insightSceneLogic.mount()
        insightData.mount()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        insightData.unmount()
        insightSceneLogic.unmount()
    })

    test.each([42, 'abc123'])('reloads a clean saved insight after an update matched by %s', async (id) => {
        await expectLogic(logic, () => {
            logic.actions.agentToolCompleted('insight-update', { id })
        }).toDispatchActions(['agentToolCompleted', 'useAiChanges', 'loadInsight'])
    })

    it('keeps a metadata draft when PostHog AI updates the insight', async () => {
        insightSceneLogic.actions.setInsightMetadataLocal({ name: 'Local name' })

        await expectLogic(logic, () => {
            logic.actions.agentToolCompleted('insight-update', { id: 42 })
        })
            .toDispatchActions(['agentToolCompleted', 'setPendingAiConflict'])
            .toMatchValues({ hasPendingAiConflict: true })
    })

    it('keeps a query draft when PostHog AI updates the insight', async () => {
        insightData.actions.setQuery({ kind: NodeKind.HogQLQuery, query: 'select 1' } as any)

        await expectLogic(logic, () => {
            logic.actions.agentToolCompleted('insight-update', { id: 42 })
        })
            .toDispatchActions(['agentToolCompleted', 'setPendingAiConflict'])
            .toMatchValues({ hasPendingAiConflict: true })
    })

    it('lets the user keep their local draft', () => {
        insightSceneLogic.actions.setInsightMetadataLocal({ name: 'Local name' })
        logic.actions.agentToolCompleted('insight-update', { id: 42 })

        logic.actions.keepMyChanges()

        expect(logic.values.hasPendingAiConflict).toBe(false)
        expect(insightSceneLogic.values.insight.name).toBe('Local name')
    })

    it('loads the saved version when the user chooses the AI update', async () => {
        insightSceneLogic.actions.setInsightMetadataLocal({ name: 'Local name' })
        logic.actions.agentToolCompleted('insight-update', { id: 42 })

        await expectLogic(logic, () => {
            logic.actions.useAiChanges()
        })
            .toDispatchActions(['useAiChanges', 'loadInsight'])
            .toMatchValues({ hasPendingAiConflict: false })
    })

    it('clears a pending conflict after a successful local save', () => {
        insightSceneLogic.actions.setInsightMetadataLocal({ name: 'Local name' })
        logic.actions.agentToolCompleted('insight-update', { id: 42 })

        insightSceneLogic.actions.saveInsightSuccess()

        expect(logic.values.hasPendingAiConflict).toBe(false)
    })

    it('ignores another insight', () => {
        expectLogic().clearHistory()

        expectLogic(logic, () => {
            logic.actions.agentToolCompleted('insight-update', { id: 99 })
        }).toNotHaveDispatchedActions(['loadInsight', 'setPendingAiConflict'])

        expect(logic.values.hasPendingAiConflict).toBe(false)
    })

    it('returns to saved insights when PostHog AI deletes the open insight', () => {
        const push = jest.spyOn(router.actions, 'push')

        logic.actions.agentToolCompleted('insight-delete', { id: 42 })

        expect(push).toHaveBeenCalledWith(urls.savedInsights())
        push.mockRestore()
    })

    it('refreshes only matching mounted subscription and alert logics', async () => {
        const mountedSubscriptions = subscriptionsLogic({ insightShortId: 'abc123' as InsightShortId })
        const mountedAlerts = insightAlertsLogic({ insightId: 42, insightLogicProps })
        mountedSubscriptions.mount()
        mountedAlerts.mount()
        mountedSubscriptions.actions.loadSubscriptionsSuccess([{ id: 10 } as any])
        mountedAlerts.actions.loadAlertsSuccess([{ id: 'alert-1' } as any])
        const loadAllSubscriptions = jest.spyOn(mountedSubscriptions.actions, 'loadAllSubscriptions')
        const loadAlerts = jest.spyOn(mountedAlerts.actions, 'loadAlerts')

        logic.actions.agentToolCompleted('subscriptions-create', { insight: 42 })
        logic.actions.agentToolCompleted('subscriptions-delete', { id: 10 })
        logic.actions.agentToolCompleted('alert-create', { insight: 42 })
        logic.actions.agentToolCompleted('alert-delete', { id: 'alert-1' })
        logic.actions.agentToolCompleted('subscriptions-delete', { id: 11 })
        logic.actions.agentToolCompleted('alert-delete', { id: 'alert-2' })

        expect(loadAllSubscriptions).toHaveBeenCalledTimes(2)
        expect(loadAlerts).toHaveBeenCalledTimes(2)

        mountedAlerts.unmount()
        mountedSubscriptions.unmount()
    })

    it('does not mount alert or subscription logic to refresh an agent change', () => {
        expect(subscriptionsLogic.isMounted({ insightShortId: 'abc123' as InsightShortId })).toBe(false)
        expect(insightAlertsLogic.findAllMounted()).toHaveLength(0)

        logic.actions.agentToolCompleted('subscriptions-create', { insight: 42 })
        logic.actions.agentToolCompleted('alert-create', { insight: 42 })

        expect(subscriptionsLogic.isMounted({ insightShortId: 'abc123' as InsightShortId })).toBe(false)
        expect(insightAlertsLogic.findAllMounted()).toHaveLength(0)
    })
})

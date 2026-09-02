import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { InsightLogicProps, InsightShortId, QueryBasedInsightModel } from '~/types'

import { insightAlertsLogic } from 'products/alerts/frontend/logic/insightAlertsLogic'
import { subscriptionsLogic } from 'products/subscriptions/frontend/components/Subscriptions/subscriptionsLogic'

import { urls } from '../urls'
import { insightAiSyncLogic, insightToolTargetsCurrentInsight } from './insightAiSyncLogic'
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

    test.each(['id', 'insightId', 'insight_id', 'short_id', 'shortId'])(
        'accepts the generated MCP %s alias when it names the open insight',
        (alias) => {
            expect(insightToolTargetsCurrentInsight({ [alias]: 'abc123' }, { id: 42, short_id: 'abc123' })).toBe(true)
        }
    )

    it('prefers a numeric primary key and fails closed for an ambiguous numeric short ID', () => {
        expect(insightToolTargetsCurrentInsight({ shortId: '42' }, { id: 42, short_id: '999' })).toBe(true)
        expect(insightToolTargetsCurrentInsight({ shortId: '999' }, { id: 42, short_id: '999' })).toBe(false)
        expect(
            insightToolTargetsCurrentInsight({ id: 42, short_id: 'another-insight' }, { id: 42, short_id: 'abc123' })
        ).toBe(false)
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

    it('keeps the conflict visible until the AI reload succeeds', async () => {
        insightSceneLogic.actions.setInsightMetadataLocal({ name: 'Local name' })
        logic.actions.agentToolCompleted('insight-update', { id: 42 })

        await expectLogic(logic, () => {
            logic.actions.useAiChanges()
        })
            .toDispatchActions(['useAiChanges', 'loadInsight'])
            .toMatchValues({ hasPendingAiConflict: true, isApplyingAiChanges: true })

        insightSceneLogic.actions.loadInsightSuccess({ ...insightLogicProps.cachedInsight, name: 'AI name' } as any)

        expect(logic.values).toMatchObject({ hasPendingAiConflict: false, isApplyingAiChanges: false })
    })

    it('keeps the conflict available when the AI reload fails', () => {
        insightSceneLogic.actions.setInsightMetadataLocal({ name: 'Local name' })
        logic.actions.agentToolCompleted('insight-update', { id: 42 })
        logic.actions.useAiChanges()

        insightSceneLogic.actions.loadInsightFailure('Failed to load')

        expect(logic.values).toMatchObject({ hasPendingAiConflict: true, isApplyingAiChanges: false })
    })

    it('restores a new local edit made while the AI reload is in flight', () => {
        insightSceneLogic.actions.setInsightMetadataLocal({ name: 'Old local name' })
        logic.actions.agentToolCompleted('insight-update', { id: 42 })
        logic.actions.useAiChanges()
        insightSceneLogic.actions.setInsightMetadataLocal({ name: 'New local name' })

        insightSceneLogic.actions.loadInsightSuccess({ ...insightLogicProps.cachedInsight, name: 'AI name' } as any)

        expect(logic.values).toMatchObject({ hasPendingAiConflict: true, isApplyingAiChanges: false })
        expect(insightSceneLogic.values.insight.name).toBe('New local name')
    })

    it('restores a new query edit made while the AI reload is in flight', () => {
        insightSceneLogic.actions.setInsightMetadataLocal({ name: 'Old local name' })
        logic.actions.agentToolCompleted('insight-update', { id: 42 })
        logic.actions.useAiChanges()
        const localQuery = { kind: NodeKind.HogQLQuery, query: 'select 2' } as any
        insightData.actions.setQuery(localQuery)

        insightSceneLogic.actions.loadInsightSuccess({
            ...insightLogicProps.cachedInsight,
            query: { kind: NodeKind.HogQLQuery, query: 'select 1' },
        } as any)

        expect(logic.values).toMatchObject({ hasPendingAiConflict: true, isApplyingAiChanges: false })
        expect(insightData.values.query).toEqual(localQuery)
    })

    it('clears a pending conflict after a successful local save', () => {
        insightSceneLogic.actions.setInsightMetadataLocal({ name: 'Local name' })
        logic.actions.agentToolCompleted('insight-update', { id: 42 })

        insightSceneLogic.actions.saveInsightSuccess()

        expect(logic.values.hasPendingAiConflict).toBe(false)
    })

    it('restores a completed local save after an older AI reload succeeds', () => {
        insightSceneLogic.actions.setInsightMetadataLocal({ name: 'Draft name' })
        logic.actions.agentToolCompleted('insight-update', { id: 42 })
        logic.actions.useAiChanges()

        const savedQuery = { kind: NodeKind.HogQLQuery, query: 'select 2' } as any
        const savedInsight = {
            ...insightLogicProps.cachedInsight,
            name: 'Saved name',
            query: savedQuery,
        } as any

        // This is insightLogic's real save completion ordering: success, then the persistent result.
        insightSceneLogic.actions.saveInsightSuccess()
        insightSceneLogic.actions.setInsight(savedInsight, { fromPersistentApi: true, overrideQuery: true })

        insightSceneLogic.actions.loadInsightSuccess({
            ...insightLogicProps.cachedInsight,
            name: 'AI name',
            query: { kind: NodeKind.HogQLQuery, query: 'select 1' },
        } as any)

        expect(insightSceneLogic.values.insight.name).toBe('Saved name')
        expect(insightSceneLogic.values.savedInsight.name).toBe('Saved name')
        expect(insightData.values.query).toEqual(savedQuery)
        expect(logic.values).toMatchObject({ hasPendingAiConflict: false, isApplyingAiChanges: false })
    })

    it('keeps edits made after a save when the older AI reload settles', () => {
        insightSceneLogic.actions.setInsightMetadataLocal({ name: 'Draft name' })
        logic.actions.agentToolCompleted('insight-update', { id: 42 })
        logic.actions.useAiChanges()

        const savedQuery = { kind: NodeKind.HogQLQuery, query: 'select 2' } as any
        insightSceneLogic.actions.saveInsightSuccess()
        insightSceneLogic.actions.setInsight(
            { ...insightLogicProps.cachedInsight, name: 'Saved name', query: savedQuery } as any,
            { fromPersistentApi: true, overrideQuery: true }
        )

        const postSaveQuery = { kind: NodeKind.HogQLQuery, query: 'select 3' } as any
        insightSceneLogic.actions.setInsightMetadataLocal({ name: 'Post-save name' })
        insightData.actions.setQuery(postSaveQuery)

        insightSceneLogic.actions.loadInsightSuccess({
            ...insightLogicProps.cachedInsight,
            name: 'AI name',
            query: { kind: NodeKind.HogQLQuery, query: 'select 1' },
        } as any)

        expect(insightSceneLogic.values.insight.name).toBe('Post-save name')
        expect(insightSceneLogic.values.savedInsight.name).toBe('Saved name')
        expect(insightData.values.query).toEqual(postSaveQuery)
        expect(logic.values).toMatchObject({ hasPendingAiConflict: false, isApplyingAiChanges: false })
        expect(insightSceneLogic.values.insightChanged).toBe(true)
        expect(insightData.values.queryChanged).toBe(true)
    })

    it('starts a second matching AI reload without restoring an earlier save', () => {
        insightSceneLogic.actions.setInsightMetadataLocal({ name: 'Draft name' })
        logic.actions.agentToolCompleted('insight-update', { id: 42 })
        logic.actions.useAiChanges()

        insightSceneLogic.actions.saveInsightSuccess()
        insightSceneLogic.actions.setInsight({ ...insightLogicProps.cachedInsight, name: 'Saved name' } as any, {
            fromPersistentApi: true,
            overrideQuery: true,
        })

        logic.actions.agentToolCompleted('insight-update', { id: 42 })
        insightSceneLogic.actions.loadInsightSuccess({
            ...insightLogicProps.cachedInsight,
            name: 'Second AI name',
        } as any)

        expect(insightSceneLogic.values.insight.name).toBe('Second AI name')
        expect(insightSceneLogic.values.savedInsight.name).toBe('Second AI name')
        expect(logic.values).toMatchObject({ hasPendingAiConflict: false, isApplyingAiChanges: false })
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
        const unrelatedSubscriptions = subscriptionsLogic({ insightShortId: 'other-insight' as InsightShortId })
        const unrelatedAlerts = insightAlertsLogic({ insightId: 99, insightLogicProps })
        mountedSubscriptions.mount()
        mountedAlerts.mount()
        unrelatedSubscriptions.mount()
        unrelatedAlerts.mount()
        mountedSubscriptions.actions.loadSubscriptionsSuccess([{ id: 10 } as any])
        mountedAlerts.actions.loadAlertsSuccess([{ id: 'alert-1' } as any])
        const loadAllSubscriptions = jest.spyOn(mountedSubscriptions.actions, 'loadAllSubscriptions')
        const loadAlerts = jest.spyOn(mountedAlerts.actions, 'loadAlerts')
        const loadUnrelatedSubscriptions = jest.spyOn(unrelatedSubscriptions.actions, 'loadAllSubscriptions')
        const loadUnrelatedAlerts = jest.spyOn(unrelatedAlerts.actions, 'loadAlerts')

        logic.actions.agentToolCompleted('subscriptions-create', { insight: 42 })
        logic.actions.agentToolCompleted('subscriptions-delete', { id: 10 })
        logic.actions.agentToolCompleted('subscriptions-partial-update', { id: 10 })
        logic.actions.agentToolCompleted('alert-create', { insight: 42 })
        logic.actions.agentToolCompleted('alert-delete', { id: 'alert-1' })
        logic.actions.agentToolCompleted('alert-update', { id: 'alert-1' })
        logic.actions.agentToolCompleted('subscriptions-delete', { id: 11 })
        logic.actions.agentToolCompleted('alert-delete', { id: 'alert-2' })

        expect(loadAllSubscriptions).toHaveBeenCalledTimes(3)
        expect(loadAlerts).toHaveBeenCalledTimes(3)
        expect(loadUnrelatedSubscriptions).not.toHaveBeenCalled()
        expect(loadUnrelatedAlerts).not.toHaveBeenCalled()

        unrelatedAlerts.unmount()
        unrelatedSubscriptions.unmount()
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

import { MOCK_TEAM_ID } from 'lib/api.mock'

import { combineUrl, router } from 'kea-router'
import { expectLogic, partial } from 'kea-test-utils'

import { addProjectIdIfMissing } from 'lib/utils/kea-router'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { examples } from '~/queries/examples'
import { InsightVizNode, NodeKind, ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { ActivityScope, InsightShortId, InsightType, ItemMode } from '~/types'

const Insight12 = '12' as InsightShortId
const Insight42 = '42' as InsightShortId

describe('insightSceneLogic', () => {
    let logic: ReturnType<typeof insightSceneLogic.build>
    beforeEach(async () => {
        useMocks({
            get: {
                '/api/environments/:team_id/insights/trend/': { result: ['result from api'] },
                '/api/environments/:team_id/insights/': {
                    results: [{ id: 42, short_id: Insight42, result: ['result from api'] }],
                },
            },
            post: {
                '/api/environments/:team_id/insights/funnel/': { result: ['result from api'] },
                '/api/environments/:team_id/insights/': async ({ request }) => [
                    200,
                    { id: 12, short_id: Insight12, ...((await request.json()) as any) },
                ],
                '/api/environments/:team_id/query/upgrade/': { query: {} },
            },
        })
        initKeaTests()
        sceneLogic.mount()
    })

    it('keeps url /insight/new', async () => {
        router.actions.push(urls.insightNew())
        logic = insightSceneLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        await expectLogic(router)
            .delay(1)
            .toMatchValues({
                location: partial({ pathname: addProjectIdIfMissing(urls.insightNew(), MOCK_TEAM_ID) }),
            })
    })

    it('disables discussions for an unsaved insight so comments do not leak across the team', async () => {
        // A new insight has no numeric id yet. The side panel context must still declare the Insight
        // scope (so sidePanelContextLogic does not fall back to the URL guesser and drop item_id, which
        // would list every Insight-scoped comment in the team) but mark discussions disabled.
        router.actions.push(urls.insightNew())
        logic = insightSceneLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.insight?.id).toBeUndefined()
        expect(logic.values.sidePanelContext).toEqual({
            activity_scope: ActivityScope.INSIGHT,
            discussions_disabled: true,
        })

        // Once saved, the context carries the concrete item_id and discussions become enabled.
        logic.values.insightLogicRef?.logic.actions.setInsight(
            { id: 42, short_id: Insight42, result: ['some result'] },
            { fromPersistentApi: true, overrideQuery: true }
        )

        expect(logic.values.sidePanelContext).toMatchObject({
            activity_scope: ActivityScope.INSIGHT,
            activity_item_id: '42',
        })
        expect(logic.values.sidePanelContext?.discussions_disabled).toBeUndefined()
    })

    it('redirects maintaining url params when opening /insight/new with insight type in theurl', async () => {
        router.actions.push(urls.insightNew({ type: InsightType.FUNNELS }))
        logic = insightSceneLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect((logic.values.insightLogicRef?.logic.values.insight.query as InsightVizNode).source?.kind).toEqual(
            'FunnelsQuery'
        )
    })

    it('tags new default insights with product_analytics productKey', async () => {
        router.actions.push(urls.insightNew())
        logic = insightSceneLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        const query = logic.values.insightLogicRef?.logic.values.insight.query as InsightVizNode
        expect(query.source?.tags?.productKey).toEqual(ProductKey.PRODUCT_ANALYTICS)
    })

    it('tags new typed insights with product_analytics productKey', async () => {
        router.actions.push(urls.insightNew({ type: InsightType.FUNNELS }))
        logic = insightSceneLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        const query = logic.values.insightLogicRef?.logic.values.insight.query as InsightVizNode
        expect(query.source?.tags?.productKey).toEqual(ProductKey.PRODUCT_ANALYTICS)
    })

    it('does not overwrite existing productKey tags on queries from URL', async () => {
        router.actions.push(
            urls.insightNew({
                query: {
                    kind: NodeKind.InsightVizNode,
                    source: {
                        ...examples.InsightTrendsQuery,
                        tags: { productKey: ProductKey.WEB_ANALYTICS },
                    },
                } as InsightVizNode,
            })
        )
        logic = insightSceneLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        const query = logic.values.insightLogicRef?.logic.values.insight.query as InsightVizNode
        expect(query.source?.tags?.productKey).toEqual(ProductKey.WEB_ANALYTICS)
    })

    it('redirects maintaining url params when opening /insight/new with query in the url', async () => {
        router.actions.push(
            urls.insightNew({
                query: {
                    kind: NodeKind.InsightVizNode,
                    source: examples.InsightPathsQuery,
                } as InsightVizNode,
            })
        )
        logic = insightSceneLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['upgradeQuery']).toFinishAllListeners()
    })

    it('retains the #q= query hash after navigating to /insights/new (persons modal drill-down)', async () => {
        // Mirrors PersonsModal's "View events" / "Open as new insight" navigation: a DataTableNode
        // query encoded in the #q= hash must survive the post-load URL sync, otherwise both buttons
        // collapse onto the same default insight page.
        const dataTableQuery = {
            kind: NodeKind.DataTableNode,
            source: {
                kind: NodeKind.EventsQuery,
                select: ['*'],
            },
        }
        router.actions.push(urls.insightNew({ query: dataTableQuery as any }))
        logic = insightSceneLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        await expectLogic(router)
            .delay(1)
            .toMatchValues({
                hashParams: partial({ q: JSON.stringify(dataTableQuery) }),
            })
    })

    it('tags a DataTableNode drill-down query on cold load via the upgrade path', async () => {
        // The persons-modal "View events" button opens in a new tab, so the scene cold-loads with the
        // query already in the URL (initial navigation -> upgradeQuery). A DataTableNode's source query
        // is executed directly, so without a productKey tag ClickHouse rejects it as untagged — the
        // upgrade path must tag the source when materializing the new insight.
        const dataTableQuery = {
            kind: NodeKind.DataTableNode,
            source: {
                kind: NodeKind.ActorsQuery,
                select: ['person'],
            },
        }
        router.actions.push(urls.insightNew({ query: dataTableQuery as any }))
        logic = insightSceneLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['upgradeQuery']).toFinishAllListeners()

        const query = logic.values.insightLogicRef?.logic.values.insight.query as any
        expect(query.kind).toEqual(NodeKind.DataTableNode)
        expect(query.source?.tags?.productKey).toEqual(ProductKey.PRODUCT_ANALYTICS)
    })

    it('tags a DataTableNode drill-down query on in-app navigation', async () => {
        // The "Open as new insight" button navigates in-app (router PUSH, not an initial load), which
        // routes through urlToAction's PUSH branch rather than upgradeQuery. That path must tag too.
        const dataTableQuery = {
            kind: NodeKind.DataTableNode,
            source: {
                kind: NodeKind.ActorsQuery,
                select: ['person'],
            },
        }

        // Settle a new-insight scene first, then navigate in-app to the drill-down query
        router.actions.push(urls.insightNew())
        logic = insightSceneLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        router.actions.push(urls.insightNew({ query: dataTableQuery as any }))
        await expectLogic(logic).toFinishAllListeners()

        const query = logic.values.insightLogicRef?.logic.values.insight.query as any
        expect(query.kind).toEqual(NodeKind.DataTableNode)
        expect(query.source?.tags?.productKey).toEqual(ProductKey.PRODUCT_ANALYTICS)
    })

    it('does not overwrite an existing productKey on a DataTableNode drill-down query', async () => {
        // A drill-down query that already declares its product (e.g. web analytics) must keep it.
        const dataTableQuery = {
            kind: NodeKind.DataTableNode,
            source: {
                kind: NodeKind.ActorsQuery,
                select: ['person'],
                tags: { productKey: ProductKey.WEB_ANALYTICS },
            },
        }
        router.actions.push(urls.insightNew({ query: dataTableQuery as any }))
        logic = insightSceneLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        const query = logic.values.insightLogicRef?.logic.values.insight.query as any
        expect(query.source?.tags?.productKey).toEqual(ProductKey.WEB_ANALYTICS)
    })

    it('does not inject tags into a DataTableNode with an EventsNode source', async () => {
        // EventsNode forbids extra keys in its schema, so tagging it would produce an invalid query.
        // The source must be left untouched (no tags field added).
        const dataTableQuery = {
            kind: NodeKind.DataTableNode,
            source: {
                kind: NodeKind.EventsNode,
                event: '$pageview',
            },
        }
        router.actions.push(urls.insightNew({ query: dataTableQuery as any }))
        logic = insightSceneLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        const query = logic.values.insightLogicRef?.logic.values.insight.query as any
        expect(query.source.kind).toEqual(NodeKind.EventsNode)
        expect(query.source.tags).toBeUndefined()
    })

    it('persists edit mode in the url', async () => {
        logic = insightSceneLogic()
        logic.mount()
        const viewUrl = combineUrl(urls.insightView(Insight42))
        const editUrl = combineUrl(urls.insightEdit(Insight42))

        router.actions.push(viewUrl.url)
        await expectLogic(logic).toMatchValues({
            insightId: Insight42,
            insightMode: ItemMode.View,
        })

        router.actions.push(editUrl.url)
        await expectLogic(logic).toMatchValues({
            insightId: Insight42,
            insightMode: ItemMode.Edit,
        })
    })

    it('resets insight state when navigating to /insights/new again after previous visit', async () => {
        router.actions.push(urls.insightNew({ type: InsightType.TRENDS, dashboardId: 6 }))
        logic = insightSceneLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        // Simulate having saved the insight by setting the insight with an id
        logic.values.insightLogicRef?.logic.actions.setInsight(
            {
                id: 99,
                short_id: '12345678' as InsightShortId,
                name: 'Saved insight',
                dashboards: [6],
                result: ['some result'],
            },
            { fromPersistentApi: true, overrideQuery: true }
        )

        expect(logic.values.insightLogicRef?.logic.values.insight.id).toEqual(99)

        // Simulate the Insight scene being active so the early-return guard in urlToAction fires
        sceneLogic.actions.setExportedScene(
            { logic: insightSceneLogic, component: () => null as any },
            Scene.Insight,
            'insightNew',
            { params: {}, searchParams: {}, hashParams: {} }
        )
        sceneLogic.actions.setScene(
            Scene.Insight,
            'insightNew',
            { params: {}, searchParams: {}, hashParams: {} },
            false
        )

        router.actions.push(urls.insightNew({ type: InsightType.RETENTION, dashboardId: 6 }))
        await expectLogic(logic).toFinishAllListeners()

        // The insight should be reset - no id means it's a new unsaved insight
        expect(logic.values.insightLogicRef?.logic.values.insight.id).toBeUndefined()
        expect(logic.values.insightLogicRef?.logic.values.insight.dashboards).toEqual([6])
    })

    it('remounts when URL insight id disagrees with dashboard tile id on the mounted editor (save-as regression)', async () => {
        useMocks({
            get: {
                '/api/environments/:team_id/insights/trend/': { result: ['result from api'] },
                '/api/environments/:team_id/insights/': ({ request }) => {
                    const shortId = new URL(request.url).searchParams.get('short_id') || ''
                    const id = shortId === '12' ? 12 : 42
                    const sid = (shortId === '12' ? Insight12 : Insight42) as InsightShortId
                    return [
                        200,
                        {
                            results: [
                                {
                                    id,
                                    short_id: sid,
                                    result: ['result from api'],
                                    name: shortId === '12' ? 'copy' : 'original',
                                },
                            ],
                        },
                    ]
                },
            },
            post: {
                '/api/environments/:team_id/insights/funnel/': { result: ['result from api'] },
                '/api/environments/:team_id/insights/': async ({ request }) => [
                    200,
                    { id: 12, short_id: Insight12, ...((await request.json()) as any) },
                ],
                '/api/environments/:team_id/query/upgrade/': { query: {} },
            },
        })

        logic = insightSceneLogic()
        logic.mount()

        router.actions.push(urls.insightEdit(Insight42))
        await expectLogic(logic).toFinishAllListeners()

        const refBefore = logic.values.insightLogicRef
        expect(refBefore?.logic.props.dashboardItemId).toBe(Insight42)
        expect(refBefore?.logic.values.insight.short_id).toBe(Insight42)

        // Stale state from the old save-as flow: copy loaded in the editor while props still target the tile.
        refBefore?.logic.actions.setInsight(
            {
                id: 12,
                short_id: Insight12,
                name: 'copy',
                query: examples.InsightFunnels,
                result: [],
            },
            { fromPersistentApi: true, overrideQuery: true }
        )

        expect(refBefore?.logic.values.insight.short_id).toBe(Insight12)

        router.actions.push(urls.insightEdit(Insight12))
        await expectLogic(logic).toFinishAllListeners()
        await expectLogic(logic).toDispatchActions(['setInsightLogicRef']).toFinishAllListeners()

        const refAfter = logic.values.insightLogicRef
        expect(refAfter).not.toBe(refBefore)
        expect(refAfter?.logic.props.dashboardItemId).toBe(Insight12)
        await expectLogic(refAfter!.logic).toFinishAllListeners()
        expect(refAfter?.logic.values.insight.short_id).toBe(Insight12)
    })

    it('reloads insight when navigating back to the same insight via PUSH', async () => {
        const insightApiCall = jest
            .fn()
            .mockReturnValue([200, { results: [{ id: 42, short_id: Insight42, result: ['result from api'] }] }])
        useMocks({
            get: {
                '/api/environments/:team_id/insights/': insightApiCall,
            },
            post: {
                '/api/environments/:team_id/query/upgrade/': { query: {} },
            },
        })

        logic = insightSceneLogic()
        logic.mount()

        router.actions.push(urls.insightView(Insight42))
        await expectLogic(logic).toMatchValues({ insightId: Insight42 })
        await expectLogic(logic).delay(150) // wait for loadInsight debounce

        // Simulate the Insight scene being active so the early-return guard fires,
        // just like in production when the user is already viewing an insight
        sceneLogic.actions.setExportedScene(
            { logic: insightSceneLogic, component: () => null as any },
            Scene.Insight,
            'insightView',
            { params: {}, searchParams: {}, hashParams: {} }
        )
        sceneLogic.actions.setScene(
            Scene.Insight,
            'insightView',
            { params: {}, searchParams: {}, hashParams: {} },
            false
        )

        const callCountAfterInitialLoad = insightApiCall.mock.calls.length

        // Simulate navigating away and back to the same insight (e.g. from insights list)
        router.actions.push(urls.insightView(Insight42))
        await expectLogic(logic).delay(150)

        // Should have reloaded the insight since this is a PUSH navigation,
        // even though activeSceneId is already Scene.Insight with the same insightId
        expect(insightApiCall.mock.calls.length).toBeGreaterThan(callCountAfterInitialLoad)
    })

    it.each([
        ['new subscription', 'new', 'new'],
        ['a specific subscription', '5', 5],
    ])(
        'updates itemId when navigating from subscriptions list to %s',
        async (_label, subscriptionId, expectedItemId) => {
            logic = insightSceneLogic()
            logic.mount()

            router.actions.push(urls.insightSubcriptions(Insight42))
            await expectLogic(logic).toMatchValues({
                insightId: Insight42,
                insightMode: ItemMode.Subscriptions,
                itemId: null,
            })

            sceneLogic.actions.setExportedScene(
                { logic: insightSceneLogic, component: () => null as any },
                Scene.Insight,
                'insightSubcriptions',
                { params: {}, searchParams: {}, hashParams: {} }
            )
            sceneLogic.actions.setScene(
                Scene.Insight,
                'insightSubcriptions',
                { params: {}, searchParams: {}, hashParams: {} },
                false
            )

            router.actions.push(urls.insightSubcription(Insight42, subscriptionId))
            await expectLogic(logic).toMatchValues({
                insightId: Insight42,
                insightMode: ItemMode.Subscriptions,
                itemId: expectedItemId,
            })
        }
    )

    it('does not reload insight when only the URL hash changes', async () => {
        const insightApiCall = jest
            .fn()
            .mockReturnValue([200, { results: [{ id: 42, short_id: Insight42, result: ['result from api'] }] }])
        useMocks({
            get: {
                '/api/environments/:team_id/insights/': insightApiCall,
            },
            post: {
                '/api/environments/:team_id/query/upgrade/': { query: {} },
            },
        })

        logic = insightSceneLogic()
        logic.mount()

        router.actions.push(urls.insightView(Insight42))
        await expectLogic(logic).toMatchValues({ insightId: Insight42 })
        await expectLogic(logic).delay(150) // wait for loadInsight debounce

        const callCountAfterInitialLoad = insightApiCall.mock.calls.length

        // Simulate opening the side panel (hash-only URL change)
        router.actions.replace(urls.insightView(Insight42), {}, { panel: 'info' })
        await expectLogic(logic).delay(150)

        expect(insightApiCall.mock.calls.length).toEqual(callCountAfterInitialLoad)
    })
})

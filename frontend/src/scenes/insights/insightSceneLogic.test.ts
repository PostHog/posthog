import { combineUrl, router } from 'kea-router'
import { expectLogic, partial } from 'kea-test-utils'
import { MOCK_TEAM_ID } from 'lib/api.mock'
import { addProjectIdIfMissing } from 'lib/utils/router-utils'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { examples } from '~/queries/examples'
import { InsightVizNode, NodeKind } from '~/queries/schema'
import { initKeaTests } from '~/test/init'
import { InsightShortId, InsightType, ItemMode } from '~/types'

const Insight12 = '12' as InsightShortId
const Insight42 = '42' as InsightShortId

describe('insightSceneLogic', () => {
    let logic: ReturnType<typeof insightSceneLogic.build>
    beforeEach(async () => {
        useMocks({
            get: {
                '/api/projects/:team/insights/trend/': { result: ['result from api'] },
            },
            post: {
                '/api/projects/:team/insights/funnel/': { result: ['result from api'] },
                '/api/projects/:team/insights/': (req) => [
                    200,
                    { id: 12, short_id: Insight12, ...((req.body as any) || {}) },
                ],
            },
        })
        initKeaTests()
        logic = insightSceneLogic()
        logic.mount()
    })

    it('keeps url /insight/new', async () => {
        router.actions.push(urls.insightNew())
        await expectLogic(logic).toFinishAllListeners()
        await expectLogic(router)
            .delay(1)
            .toMatchValues({
                location: partial({ pathname: addProjectIdIfMissing(urls.insightNew(), MOCK_TEAM_ID) }),
            })
    })

    it('redirects when opening /insight/new with insight type in theurl', async () => {
        router.actions.push(urls.insightNew(InsightType.FUNNELS))
        await expectLogic(logic).toFinishAllListeners()
        await expectLogic(router)
            .delay(1)
            .toMatchValues({
                location: partial({
                    pathname: addProjectIdIfMissing(urls.insightNew(), MOCK_TEAM_ID),
                    search: '',
                    hash: '',
                }),
            })

        expect((logic.values.insightLogicRef?.logic.values.insight.query as InsightVizNode).source?.kind).toEqual(
            'FunnelsQuery'
        )
    })

    it('redirects when opening /insight/new with query in the url', async () => {
        router.actions.push(
            urls.insightNew(undefined, undefined, {
                kind: NodeKind.InsightVizNode,
                source: examples.InsightPathsQuery,
            } as InsightVizNode)
        )
        await expectLogic(logic).toFinishAllListeners()
        await expectLogic(router)
            .delay(1)
            .toMatchValues({
                location: partial({
                    pathname: addProjectIdIfMissing(urls.insightNew(), MOCK_TEAM_ID),
                    search: '',
                    hash: '',
                }),
            })

        expect((logic.values.insightLogicRef?.logic.values.insight.query as InsightVizNode).source?.kind).toEqual(
            'PathsQuery'
        )
    })

    it('persists edit mode in the url', async () => {
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
})

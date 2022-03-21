import { combineUrl, router } from 'kea-router'
import { urls } from 'scenes/urls'
import { expectLogic, partial } from 'kea-test-utils'
import { InsightShortId, InsightType, ItemMode } from '~/types'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'
import { initKeaTests } from '~/test/init'
import { useMocks } from '~/mocks/jest'

const Insight12 = '12' as InsightShortId
const Insight42 = '42' as InsightShortId

describe('insightSceneLogic', () => {
    let logic: ReturnType<typeof insightSceneLogic.build>
    beforeEach(async () => {
        useMocks({
            post: {
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

    it('redirects when opening /insight/new', async () => {
        router.actions.push(urls.insightNew({ insight: InsightType.FUNNELS }))
        await expectLogic(logic).toFinishAllListeners()
        await expectLogic(router)
            .delay(1)
            .toMatchValues({
                location: partial({ pathname: urls.insightEdit(Insight12) }),
            })
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

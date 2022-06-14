import { expectLogic } from 'kea-test-utils'
import { initKeaTests } from '~/test/init'
import { useMocks } from '~/mocks/jest'
import { insightSubscriptionsLogic } from './insightSubscriptionsLogic'
import { InsightModel, InsightShortId, InsightType, PropertyOperator, SubscriptionType } from '~/types'
import { insightLogic } from 'scenes/insights/insightLogic'

const Insight1 = '1' as InsightShortId
const Insight2 = '2' as InsightShortId

export const fixtureSubscriptionResponse = (id: number, args: Partial<SubscriptionType> = {}): SubscriptionType =>
    ({
        id,
        title: 'My example subscription',
        target_type: 'email',
        target_value: 'ben@posthog.com,geoff@other-company.com',
        frequency: 'monthly',
        interval: 2,
        start_date: '2022-01-01T00:09:00',
        byweekday: ['wednesday'],
        bysetpos: 1,
        ...args,
    } as SubscriptionType)

const API_FILTERS = {
    insight: InsightType.TRENDS as InsightType,
    events: [{ id: 3 }],
    properties: [{ value: 'a', operator: PropertyOperator.Exact, key: 'a', type: 'a' }],
}
function fixtureInsightResponse(id: number, data?: Partial<InsightModel>): Partial<InsightModel> {
    return {
        id: id,
        short_id: id.toString() as InsightShortId,
        name: 'insight',
        result: [`result ${id}`],
        filters: API_FILTERS,
        ...data,
    }
}

describe('insightSubscriptionsLogic', () => {
    let logic: ReturnType<typeof insightSubscriptionsLogic.build>
    let subscriptions: SubscriptionType[] = []
    beforeEach(async () => {
        subscriptions = [fixtureSubscriptionResponse(1), fixtureSubscriptionResponse(2)]
        useMocks({
            get: {
                '/api/projects/:team/insights/1': fixtureInsightResponse(1),
                '/api/projects/:team/insights/2': fixtureInsightResponse(2),
                '/api/projects/:team/insights': (req) => {
                    const insightShortId = req.url.searchParams.get('short_id')
                    const res = insightShortId ? [fixtureInsightResponse(parseInt(insightShortId, 10))] : []
                    return [200, { results: res }]
                },

                '/api/projects/:team/subscriptions': (req) => {
                    const insightId = req.url.searchParams.get('insight_id')
                    let results: SubscriptionType[] = []

                    if (insightId === Insight2) {
                        results = subscriptions
                    }

                    return [
                        200,
                        {
                            results,
                            count: results.length,
                        },
                    ]
                },
            },
        })
        initKeaTests()
        logic = insightSubscriptionsLogic({
            insightShortId: Insight1,
        })
        logic.mount()
    })

    it('mounts other logics', async () => {
        await expectLogic(logic).toMount([insightLogic({ dashboardItemId: Insight1 })])
    })

    it('loads subscriptions', async () => {
        await expectLogic(logic).delay(1).toMatchValues({
            subscriptions: [],
            subscriptionsLoading: false,
        })

        logic = insightSubscriptionsLogic({
            insightShortId: Insight2,
        })
        logic.mount()

        await expectLogic(logic).toFinishListeners()
        await expectLogic(logic).delay(100).toMatchValues({
            subscriptions: subscriptions,
            subscriptionsLoading: false,
        })
    })
})

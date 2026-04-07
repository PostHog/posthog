import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import {
    FilterType,
    InsightModel,
    InsightShortId,
    InsightType,
    PropertyFilterType,
    PropertyOperator,
    SubscriptionType,
} from '~/types'

import { subscriptionsLogic } from './subscriptionsLogic'

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
    }) as SubscriptionType

const API_FILTERS: Partial<FilterType> = {
    insight: InsightType.TRENDS as InsightType,
    events: [{ id: 3 }],
    properties: [{ value: 'a', operator: PropertyOperator.Exact, key: 'a', type: PropertyFilterType.Person }],
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

describe('subscriptionsLogic', () => {
    let logic: ReturnType<typeof subscriptionsLogic.build>
    let subscriptions: SubscriptionType[] = []
    beforeEach(async () => {
        subscriptions = [fixtureSubscriptionResponse(1), fixtureSubscriptionResponse(2)]
        useMocks({
            get: {
                '/api/environments/:team_id/insights/1': fixtureInsightResponse(1),
                '/api/environments/:team_id/insights/2': fixtureInsightResponse(2),
                '/api/environments/:team_id/insights': (req) => {
                    const insightShortId = req.url.searchParams.get('short_id')
                    const res = insightShortId ? [fixtureInsightResponse(parseInt(insightShortId, 10))] : []
                    return [200, { results: res }]
                },

                '/api/environments/:team_id/subscriptions': (req) => {
                    const insightId = req.url.searchParams.get('insight')
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
        logic = subscriptionsLogic({
            insightShortId: Insight1,
        })
        logic.mount()
    })

    it('loads subscriptions', async () => {
        await expectLogic(logic).toFinishListeners().toMatchValues({
            subscriptions: [],
            subscriptionsLoading: false,
        })

        logic = subscriptionsLogic({
            insightShortId: Insight2,
        })
        logic.mount()

        await expectLogic(logic).toFinishListeners().toMatchValues({
            subscriptions: subscriptions,
            subscriptionsLoading: false,
        })
    })
})

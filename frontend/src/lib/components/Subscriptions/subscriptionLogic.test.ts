import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { InsightShortId, SubscriptionType } from '~/types'

import { subscriptionLogic } from './subscriptionLogic'

const Insight1 = '1' as InsightShortId

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

describe('subscriptionLogic', () => {
    let newLogic: ReturnType<typeof subscriptionLogic.build>
    let existingLogic: ReturnType<typeof subscriptionLogic.build>
    let subscriptions: SubscriptionType[] = []
    beforeEach(async () => {
        subscriptions = [fixtureSubscriptionResponse(1), fixtureSubscriptionResponse(2)]
        useMocks({
            get: {
                '/api/projects/:team/subscriptions/1': fixtureSubscriptionResponse(1),
            },
        })
        initKeaTests()
        newLogic = subscriptionLogic({
            insightShortId: Insight1,
            id: 'new',
        })
        existingLogic = subscriptionLogic({
            insightShortId: Insight1,
            id: subscriptions[0].id,
        })
        newLogic.mount()
        existingLogic.mount()
    })

    it('updates values depending on frequency', async () => {
        router.actions.push('/insights/123/subscriptions/new')
        await expectLogic(newLogic).toFinishListeners()
        expect(newLogic.values.subscription).toMatchObject({
            frequency: 'weekly',
            bysetpos: 1,
            byweekday: ['monday'],
        })

        newLogic.actions.setSubscriptionValue('frequency', 'daily')
        await expectLogic(newLogic).toFinishListeners()
        expect(newLogic.values.subscription).toMatchObject({
            frequency: 'daily',
            bysetpos: null,
            byweekday: null,
        })

        newLogic.actions.setSubscriptionValue('frequency', 'monthly')
        await expectLogic(newLogic).toFinishListeners()
        expect(newLogic.values.subscription).toMatchObject({
            frequency: 'monthly',
            bysetpos: 1,
            byweekday: ['monday'],
        })
    })

    it('sets the type from query params', async () => {
        router.actions.push('/insights/123/subscriptions/new?target_type=slack')
        await expectLogic(newLogic).toFinishListeners()
        expect(newLogic.values.subscription).toMatchObject({
            target_type: 'slack',
        })
    })
})

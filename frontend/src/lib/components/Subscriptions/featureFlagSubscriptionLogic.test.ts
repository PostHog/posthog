import { expectLogic } from 'kea-test-utils'
import { initKeaTests } from '~/test/init'
import { useMocks } from '~/mocks/jest'
import { SubscriptionType } from '~/types'

import {
    featureFlagSubscriptionLogic,
    NEW_FEATURE_FLAG_SUBSCRIPTION,
} from 'lib/components/Subscriptions/featureFlagSubscriptionLogic'
import { userLogic } from 'scenes/userLogic'

export const fixtureFeatureFlagSubscriptionResponse = (
    id: number,
    args: Partial<SubscriptionType> = {}
): SubscriptionType =>
    ({
        id,
        target_type: 'in_app_notification',
        target_value: '',
        frequency: 'on_change',
        interval: 0,
        start_date: '2022-01-01T00:09:00',
        ...args,
    } as SubscriptionType)

describe('featureFlagSubscriptionLogic', () => {
    let newLogic: ReturnType<typeof featureFlagSubscriptionLogic.build>
    let existingLogic: ReturnType<typeof featureFlagSubscriptionLogic.build>
    let subscriptions: SubscriptionType[] = []
    beforeEach(async () => {
        subscriptions = [fixtureFeatureFlagSubscriptionResponse(1), fixtureFeatureFlagSubscriptionResponse(2)]
        useMocks({
            get: {
                '/api/projects/:team/subscriptions/1': fixtureFeatureFlagSubscriptionResponse(1),
                '/api/projects/:team/subscriptions': { count: subscriptions.length, results: subscriptions },
            },
        })
        initKeaTests()
        userLogic.mount()
        await expectLogic(userLogic).toFinishAllListeners()
        newLogic = featureFlagSubscriptionLogic({
            featureFlagId: 'new',
        })
        existingLogic = featureFlagSubscriptionLogic({
            featureFlagId: 1,
        })
        newLogic.mount()
        existingLogic.mount()
    })

    it('has defaults for existing feature flag subscription', async () => {
        await expectLogic(existingLogic)
            .toFinishAllListeners()
            .toMatchValues({
                subscription: {
                    ...NEW_FEATURE_FLAG_SUBSCRIPTION,
                    id: 1,
                    start_date: expect.any(String),
                },
            })
    })

    it('has defaults for new feature flag subscription', async () => {
        await expectLogic(newLogic).toFinishAllListeners().toMatchValues({
            subscription: null,
        })
    })
})

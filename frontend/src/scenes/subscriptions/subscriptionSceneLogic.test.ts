import { MOCK_TEAM_ID } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { FrequencyEnumApi, SubscriptionsDeliveriesListStatus, TargetTypeEnumApi } from '~/generated/core/api.schemas'
import type { SubscriptionApi } from '~/generated/core/api.schemas'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { subscriptionSceneLogic } from './subscriptionSceneLogic'

const MOCK_USER = {
    id: 1,
    uuid: '01863799-062b-0000-8a61-b2842d5f8642',
    email: 'test@posthog.com',
    first_name: 'Test',
    last_name: 'User',
    hedgehog_config: null,
} as const

const MOCK_SUBSCRIPTION: SubscriptionApi = {
    id: 1,
    insight: 101,
    dashboard: null,
    insight_short_id: 'abc123',
    resource_name: 'North star metric',
    title: 'Weekly rollup',
    dashboard_export_insights: [],
    target_type: TargetTypeEnumApi.Email,
    target_value: 'a@b.com',
    frequency: FrequencyEnumApi.Weekly,
    interval: 1,
    start_date: '2022-01-01T00:00:00Z',
    created_at: '2023-04-27T10:04:37.977401Z',
    created_by: MOCK_USER,
    summary: 'sent every week',
    next_delivery_date: '2026-04-07T17:00:00Z',
    deleted: false,
}

describe('subscriptionSceneLogic', () => {
    let deliveriesRequestUrls: string[]

    beforeEach(() => {
        deliveriesRequestUrls = []
    })

    it('includes status in deliveries list request when status filter is set', async () => {
        useMocks({
            get: {
                [`/api/projects/${MOCK_TEAM_ID}/subscriptions/1/`]: [200, MOCK_SUBSCRIPTION],
                [`/api/environments/${MOCK_TEAM_ID}/subscriptions/1/deliveries/`]: (req) => {
                    deliveriesRequestUrls.push(req.url.toString())
                    return [200, { results: [], next: null, previous: null }]
                },
            },
        })
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.HACKATHONS_SUBSCRIPTIONS], {
            [FEATURE_FLAGS.HACKATHONS_SUBSCRIPTIONS]: true,
        })

        const logic = subscriptionSceneLogic({ id: '1', tabId: 'tab-filter' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(deliveriesRequestUrls).toHaveLength(1)
        expect(deliveriesRequestUrls[0]).not.toContain('status=')

        await expectLogic(logic, () => {
            logic.actions.setDeliveryStatusFilter(SubscriptionsDeliveriesListStatus.Failed)
        }).toFinishAllListeners()

        expect(deliveriesRequestUrls).toHaveLength(2)
        expect(deliveriesRequestUrls[1]).toContain('status=failed')
        logic.unmount()
        featureFlagLogic.unmount()
    })

    it('does not request deliveries when the hackathons_subscriptions flag is off', async () => {
        useMocks({
            get: {
                [`/api/projects/${MOCK_TEAM_ID}/subscriptions/1/`]: [200, MOCK_SUBSCRIPTION],
                [`/api/environments/${MOCK_TEAM_ID}/subscriptions/1/deliveries/`]: () => {
                    deliveriesRequestUrls.push('deliveries')
                    return [200, { results: [], next: null, previous: null }]
                },
            },
        })
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], {})

        const logic = subscriptionSceneLogic({ id: '1', tabId: 'tab-a' })
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadSubscriptionSuccess'])
        expect(deliveriesRequestUrls).toHaveLength(0)
        logic.unmount()
        featureFlagLogic.unmount()
    })

    it('loads delivery history when the hackathons_subscriptions flag is on', async () => {
        useMocks({
            get: {
                [`/api/projects/${MOCK_TEAM_ID}/subscriptions/1/`]: [200, MOCK_SUBSCRIPTION],
                [`/api/environments/${MOCK_TEAM_ID}/subscriptions/1/deliveries/`]: () => {
                    deliveriesRequestUrls.push('deliveries')
                    return [200, { results: [], next: null, previous: null }]
                },
            },
        })
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.HACKATHONS_SUBSCRIPTIONS], {
            [FEATURE_FLAGS.HACKATHONS_SUBSCRIPTIONS]: true,
        })

        const logic = subscriptionSceneLogic({ id: '1', tabId: 'tab-b' })
        logic.mount()

        await expectLogic(logic).toFinishAllListeners()
        expect(deliveriesRequestUrls).toHaveLength(1)
        logic.unmount()
        featureFlagLogic.unmount()
    })

    it('refetches deliveries after subscription loads when the flag turns on', async () => {
        useMocks({
            get: {
                [`/api/projects/${MOCK_TEAM_ID}/subscriptions/1/`]: [200, MOCK_SUBSCRIPTION],
                [`/api/environments/${MOCK_TEAM_ID}/subscriptions/1/deliveries/`]: () => {
                    deliveriesRequestUrls.push('deliveries')
                    return [200, { results: [], next: null, previous: null }]
                },
            },
        })
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], {})

        const logic = subscriptionSceneLogic({ id: '1', tabId: 'tab-c' })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadSubscriptionSuccess'])
        expect(deliveriesRequestUrls).toHaveLength(0)

        await expectLogic(logic, () => {
            featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.HACKATHONS_SUBSCRIPTIONS], {
                [FEATURE_FLAGS.HACKATHONS_SUBSCRIPTIONS]: true,
            })
        }).toFinishAllListeners()

        expect(deliveriesRequestUrls).toHaveLength(1)
        logic.unmount()
        featureFlagLogic.unmount()
    })
})

import { MOCK_DEFAULT_USER, MOCK_USER_UUID } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { TargetTypeEnumApi } from '~/generated/core/api.schemas'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { subscriptionsSceneLogic, SubscriptionsTab } from './subscriptionsSceneLogic'

const EMPTY_SUBSCRIPTIONS = { count: 0, results: [] as unknown[] }

const blankScene = (): any => ({ scene: { component: () => null, logic: null } })
const scenes: any = { [Scene.Subscriptions]: blankScene }

function subscriptionListParamsFromUrl(url: string): URLSearchParams {
    return new URL(url).searchParams
}

describe('subscriptionsSceneLogic', () => {
    let logic: ReturnType<typeof subscriptionsSceneLogic.build>
    let subscriptionRequestUrls: string[]

    beforeEach(() => {
        subscriptionRequestUrls = []
        useMocks({
            get: {
                '/api/projects/:team_id/subscriptions/': (req) => {
                    subscriptionRequestUrls.push(req.url.toString())
                    return [200, EMPTY_SUBSCRIPTIONS]
                },
            },
        })
        initKeaTests()
        sceneLogic({ scenes }).mount()
        sceneLogic.actions.setTabs([
            { id: '1', title: '...', pathname: '/', search: '', hash: '', active: true, iconType: 'blank' },
        ])
        userLogic.mount()
        userLogic.actions.loadUserSuccess(MOCK_DEFAULT_USER)
        router.actions.push(urls.subscriptions())
        logic = subscriptionsSceneLogic({ tabId: '1' })
        logic.mount()
    })

    describe('list requests', () => {
        it('loads with default ordering -created_at', async () => {
            await expectLogic(logic).toDispatchActions(['loadSubscriptionsSuccess'])

            expect(subscriptionRequestUrls).toHaveLength(1)
            const params = subscriptionListParamsFromUrl(subscriptionRequestUrls[0])
            expect(params.get('ordering')).toBe('-created_at')
            expect(params.get('limit')).toBe('20')
            expect(params.get('offset')).toBe('0')
        })

        it('sends resource_type=dashboard on Dashboard tab', async () => {
            await expectLogic(logic).toDispatchActions(['loadSubscriptionsSuccess'])
            subscriptionRequestUrls.length = 0

            await expectLogic(logic, () => {
                logic.actions.setCurrentTab(SubscriptionsTab.Dashboard)
            }).toDispatchActions(['setCurrentTab', 'loadSubscriptions', 'loadSubscriptionsSuccess'])

            expect(subscriptionRequestUrls).toHaveLength(1)
            const params = subscriptionListParamsFromUrl(subscriptionRequestUrls[0])
            expect(params.get('resource_type')).toBe('dashboard')
        })

        it('sends resource_type=insight on Insight tab', async () => {
            await expectLogic(logic).toDispatchActions(['loadSubscriptionsSuccess'])
            subscriptionRequestUrls.length = 0

            await expectLogic(logic, () => {
                logic.actions.setCurrentTab(SubscriptionsTab.Insight)
            }).toDispatchActions(['setCurrentTab', 'loadSubscriptions', 'loadSubscriptionsSuccess'])

            expect(subscriptionRequestUrls).toHaveLength(1)
            const params = subscriptionListParamsFromUrl(subscriptionRequestUrls[0])
            expect(params.get('resource_type')).toBe('insight')
        })

        it('sends created_by for Mine tab', async () => {
            await expectLogic(logic).toDispatchActions(['loadSubscriptionsSuccess'])
            subscriptionRequestUrls.length = 0

            await expectLogic(logic, () => {
                logic.actions.setCurrentTab(SubscriptionsTab.Mine)
            }).toDispatchActions(['setCurrentTab', 'loadSubscriptions', 'loadSubscriptionsSuccess'])

            expect(subscriptionRequestUrls).toHaveLength(1)
            const params = subscriptionListParamsFromUrl(subscriptionRequestUrls[0])
            expect(params.get('created_by')).toBe(MOCK_USER_UUID)
        })

        it('maps next delivery sorting to ordering query params', async () => {
            await expectLogic(logic).toDispatchActions(['loadSubscriptionsSuccess'])
            subscriptionRequestUrls.length = 0

            await expectLogic(logic, () => {
                logic.actions.setSubscriptionsSorting({ columnKey: 'next_delivery_date', order: 1 })
            }).toDispatchActions(['setSubscriptionsSorting', 'loadSubscriptions', 'loadSubscriptionsSuccess'])

            expect(subscriptionRequestUrls).toHaveLength(1)
            let params = subscriptionListParamsFromUrl(subscriptionRequestUrls[0])
            expect(params.get('ordering')).toBe('next_delivery_date')

            subscriptionRequestUrls.length = 0
            await expectLogic(logic, () => {
                logic.actions.setSubscriptionsSorting({ columnKey: 'next_delivery_date', order: -1 })
            }).toDispatchActions(['setSubscriptionsSorting', 'loadSubscriptions', 'loadSubscriptionsSuccess'])

            expect(subscriptionRequestUrls).toHaveLength(1)
            params = subscriptionListParamsFromUrl(subscriptionRequestUrls[0])
            expect(params.get('ordering')).toBe('-next_delivery_date')
        })

        it('maps name, created by, and created sorting to ordering query params', async () => {
            await expectLogic(logic).toDispatchActions(['loadSubscriptionsSuccess'])
            subscriptionRequestUrls.length = 0

            await expectLogic(logic, () => {
                logic.actions.setSubscriptionsSorting({ columnKey: 'name', order: 1 })
            }).toDispatchActions(['setSubscriptionsSorting', 'loadSubscriptions', 'loadSubscriptionsSuccess'])
            expect(subscriptionListParamsFromUrl(subscriptionRequestUrls[0]).get('ordering')).toBe('title')

            subscriptionRequestUrls.length = 0
            await expectLogic(logic, () => {
                logic.actions.setSubscriptionsSorting({ columnKey: 'created_by', order: -1 })
            }).toDispatchActions(['setSubscriptionsSorting', 'loadSubscriptions', 'loadSubscriptionsSuccess'])
            expect(subscriptionListParamsFromUrl(subscriptionRequestUrls[0]).get('ordering')).toBe('-created_by__email')

            subscriptionRequestUrls.length = 0
            await expectLogic(logic, () => {
                logic.actions.setSubscriptionsSorting({ columnKey: 'created_at', order: 1 })
            }).toDispatchActions(['setSubscriptionsSorting', 'loadSubscriptions', 'loadSubscriptionsSuccess'])
            expect(subscriptionListParamsFromUrl(subscriptionRequestUrls[0]).get('ordering')).toBe('created_at')
        })

        it('reloads after deleteSubscriptionSuccess', async () => {
            await expectLogic(logic).toDispatchActions(['loadSubscriptionsSuccess'])
            subscriptionRequestUrls.length = 0

            await expectLogic(logic, () => {
                logic.actions.deleteSubscriptionSuccess()
            }).toDispatchActions(['deleteSubscriptionSuccess', 'loadSubscriptions', 'loadSubscriptionsSuccess'])

            expect(subscriptionRequestUrls).toHaveLength(1)
        })

        it('passes search to the list API after setSearch (debounced listener)', async () => {
            await expectLogic(logic).toDispatchActions(['loadSubscriptionsSuccess'])
            subscriptionRequestUrls.length = 0

            await expectLogic(logic, () => {
                logic.actions.setSearch('weekly')
            })
                .toFinishAllListeners()
                .toDispatchActions(['setSearch', 'loadSubscriptions', 'loadSubscriptionsSuccess'])
                .toMatchValues({ search: 'weekly' })

            expect(subscriptionRequestUrls).toHaveLength(1)
            const params = subscriptionListParamsFromUrl(subscriptionRequestUrls[0])
            expect(params.get('search')).toBe('weekly')
        })

        it('sends target_type when channel filter is set', async () => {
            await expectLogic(logic).toDispatchActions(['loadSubscriptionsSuccess'])
            subscriptionRequestUrls.length = 0

            await expectLogic(logic, () => {
                logic.actions.setTargetTypeFilter(TargetTypeEnumApi.Slack)
            }).toDispatchActions(['setTargetTypeFilter', 'loadSubscriptions', 'loadSubscriptionsSuccess'])

            expect(subscriptionRequestUrls).toHaveLength(1)
            const params = subscriptionListParamsFromUrl(subscriptionRequestUrls[0])
            expect(params.get('target_type')).toBe('slack')
        })
    })
})

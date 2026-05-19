import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { sceneLogic } from 'scenes/sceneLogic'
import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'

import { customerAnalyticsSceneLogic } from './customerAnalyticsSceneLogic'

describe('customerAnalyticsSceneLogic', () => {
    let logic: ReturnType<typeof customerAnalyticsSceneLogic.build>

    beforeEach(() => {
        initKeaTests()
        localStorage.clear()
        sceneLogic.mount()
        router.actions.push(urls.customerAnalytics())
        logic = customerAnalyticsSceneLogic({ tabId: sceneLogic.values.activeTabId || '' })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        localStorage.clear()
    })

    describe('filterTestAccounts', () => {
        it('defaults to true', () => {
            expectLogic(logic).toMatchValues({
                filterTestAccounts: true,
            })
        })

        it('can be toggled off', async () => {
            await expectLogic(logic, () => {
                logic.actions.setFilterTestAccounts(false)
            }).toMatchValues({
                filterTestAccounts: false,
            })
        })

        it('can be toggled on', async () => {
            logic.actions.setFilterTestAccounts(false)

            await expectLogic(logic, () => {
                logic.actions.setFilterTestAccounts(true)
            }).toMatchValues({
                filterTestAccounts: true,
            })
        })
    })

    describe('URL sync', () => {
        it('reads filter_test_accounts from URL', () => {
            expectLogic(logic).toMatchValues({
                filterTestAccounts: true,
            })

            router.actions.push(urls.customerAnalytics(), {
                filter_test_accounts: 'false',
            })

            expectLogic(logic).toMatchValues({
                filterTestAccounts: false,
            })
        })
    })
})

import { initKeaTests } from '~/test/init'
import { featureFlagsLogic, FeatureFlagsTabs } from 'scenes/feature-flags/featureFlagsLogic'
import { expectLogic } from 'kea-test-utils'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'

describe('the feature flags logic', () => {
    let logic: ReturnType<typeof featureFlagsLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = featureFlagsLogic()
        logic.mount()
    })

    it('starts with active tab as "overview"', async () => {
        await expectLogic(logic).toMatchValues({ activeTab: FeatureFlagsTabs.OVERVIEW })
    })

    it('can set tab to "history"', async () => {
        await expectLogic(logic, () => {
            logic.actions.setActiveTab('history')
        }).toMatchValues({ activeTab: FeatureFlagsTabs.HISTORY })
        expect(router.values.searchParams['tab']).toEqual('history')
    })

    it('can set tab back to "overview"', async () => {
        await expectLogic(logic, () => {
            logic.actions.setActiveTab('history')
            logic.actions.setActiveTab('overview')
        }).toMatchValues({ activeTab: FeatureFlagsTabs.OVERVIEW })
        expect(router.values.searchParams['tab']).toEqual('overview')
    })

    it('ignores unexpected tab keys', async () => {
        await expectLogic(logic, () => {
            logic.actions.setActiveTab('history')
            logic.actions.setActiveTab('tomato')
        }).toMatchValues({
            activeTab: FeatureFlagsTabs.HISTORY,
        })
        expect(router.values.searchParams['tab']).toEqual('history')
    })

    it('sets the tab from the URL', async () => {
        await expectLogic(logic, () => {
            logic.actions.setActiveTab(FeatureFlagsTabs.OVERVIEW)
            router.actions.push(urls.featureFlags(), { tab: 'history' })
        }).toMatchValues({
            activeTab: FeatureFlagsTabs.HISTORY,
        })
    })

    it('sets the page from the URL when on history tab', async () => {
        router.actions.push(urls.featureFlags(), { page: '4' })
        await expectLogic(logic, () => {
            logic.actions.setActiveTab(FeatureFlagsTabs.HISTORY)
        }).toMatchValues({
            historyPage: 4,
        })
    })

    it('does not set the page from the URL when on overview tab', async () => {
        router.actions.push(urls.featureFlags(), { page: '4' })
        await expectLogic(logic, () => {
            logic.actions.setActiveTab(FeatureFlagsTabs.OVERVIEW)
        }).toMatchValues({
            historyPage: null,
        })
    })
})

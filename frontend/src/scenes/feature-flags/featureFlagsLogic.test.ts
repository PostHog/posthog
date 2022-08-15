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
            logic.actions.setActiveTab(FeatureFlagsTabs.HISTORY)
        }).toMatchValues({ activeTab: FeatureFlagsTabs.HISTORY })
        expect(router.values.searchParams['tab']).toEqual('history')
    })

    it('can set tab back to "overview"', async () => {
        await expectLogic(logic, () => {
            logic.actions.setActiveTab(FeatureFlagsTabs.HISTORY)
            logic.actions.setActiveTab(FeatureFlagsTabs.OVERVIEW)
        }).toMatchValues({ activeTab: FeatureFlagsTabs.OVERVIEW })
        expect(router.values.searchParams['tab']).toEqual('overview')
    })

    it('ignores unexpected tab keys', async () => {
        await expectLogic(logic, () => {
            logic.actions.setActiveTab(FeatureFlagsTabs.HISTORY)
            logic.actions.setActiveTab('tomato' as FeatureFlagsTabs)
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
})

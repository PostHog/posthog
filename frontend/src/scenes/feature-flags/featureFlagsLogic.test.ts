import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { FeatureFlagsTab, featureFlagsLogic } from 'scenes/feature-flags/featureFlagsLogic'
import { urls } from 'scenes/urls'
import api from 'lib/api'

import { initKeaTests } from '~/test/init'

describe('the feature flags logic', () => {
    let logic: ReturnType<typeof featureFlagsLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = featureFlagsLogic()
        logic.mount()
    })

    it('starts with active tab as "overview"', async () => {
        await expectLogic(logic).toMatchValues({ activeTab: FeatureFlagsTab.OVERVIEW })
    })

    it('can set tab to "history"', async () => {
        await expectLogic(logic, () => {
            logic.actions.setActiveTab(FeatureFlagsTab.HISTORY)
        }).toMatchValues({ activeTab: FeatureFlagsTab.HISTORY })
        expect(router.values.searchParams['tab']).toEqual('history')
    })

    it('can set tab back to "overview"', async () => {
        await expectLogic(logic, () => {
            logic.actions.setActiveTab(FeatureFlagsTab.HISTORY)
            logic.actions.setActiveTab(FeatureFlagsTab.OVERVIEW)
        }).toMatchValues({ activeTab: FeatureFlagsTab.OVERVIEW })
        expect(router.values.searchParams['tab']).toEqual('overview')
    })

    it('ignores unexpected tab keys', async () => {
        await expectLogic(logic, () => {
            logic.actions.setActiveTab(FeatureFlagsTab.HISTORY)
            logic.actions.setActiveTab('tomato' as FeatureFlagsTab)
        }).toMatchValues({
            activeTab: FeatureFlagsTab.HISTORY,
        })
        expect(router.values.searchParams['tab']).toEqual('history')
    })

    it('sets the tab from the URL', async () => {
        await expectLogic(logic, () => {
            logic.actions.setActiveTab(FeatureFlagsTab.OVERVIEW)
            router.actions.push(urls.featureFlags(), { tab: 'history' })
        }).toMatchValues({
            activeTab: FeatureFlagsTab.HISTORY,
        })
    })

    describe('sorting', () => {
        beforeEach(() => {
            jest.spyOn(api, 'get')
                .mockClear()
                .mockImplementation(async (url: string) => {
                    if (url.startsWith('api/projects/')) {
                        return { results: [], count: 0 }
                    }
                    return { results: [], count: 0 }
                })
        })

        it('can set sorting order', async () => {
            await expectLogic(logic, () => {
                logic.actions.setFeatureFlagsFilters({ order: 'updated_at' })
            }).toMatchValues({
                filters: expect.objectContaining({ order: 'updated_at' }),
            })
        })

        it('reloads feature flags when sorting changes', async () => {
            await expectLogic(logic, () => {
                logic.actions.setFeatureFlagsFilters({ order: '-updated_at' })
            }).toDispatchActions(['setFeatureFlagsFilters', 'loadFeatureFlags'])
        })

        it('constructs the correct API url with ordering', async () => {
            await expectLogic(logic, () => {
                logic.actions.setFeatureFlagsFilters({ order: '-updated_at' })
            })

            // The mock is global, so it should have been called
            expect(api.get).toHaveBeenCalledWith(expect.stringContaining('order=-updated_at'))
        })
    })
})

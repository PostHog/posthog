import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { NEW_FLAG } from 'scenes/feature-flags/featureFlagLogic'
import {
    FeatureFlagsTab,
    featureFlagsLogic,
    flagMatchesSearch,
    flagMatchesStatus,
    flagMatchesType,
} from 'scenes/feature-flags/featureFlagsLogic'
import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'
import { FeatureFlagType } from '~/types'

describe('flagMatchesSearch', () => {
    const flag = { ...NEW_FLAG, id: 1, key: 'my-feature', name: 'My Feature Flag' } as FeatureFlagType

    it.each<[string | undefined, boolean]>([
        [undefined, true],
        ['my', true],
        ['MY-FEATURE', true],
        ['flag', true],
        ['nonexistent', false],
    ])('search=%p → %p', (search, expected) => {
        expect(flagMatchesSearch(flag, search)).toBe(expected)
    })
})

describe('flagMatchesStatus', () => {
    it.each<[boolean, FeatureFlagType['status'], string | undefined, boolean]>([
        [true, 'ACTIVE', undefined, true],
        [true, 'ACTIVE', 'true', true],
        [true, 'ACTIVE', 'false', false],
        [false, 'ACTIVE', 'false', true],
        [true, 'STALE', 'STALE', true],
        [true, 'ACTIVE', 'STALE', false],
    ])('active=%p status=%p filter=%p → %p', (active, status, filter, expected) => {
        const flag = { ...NEW_FLAG, id: 1, key: 'test', active, status } as FeatureFlagType
        expect(flagMatchesStatus(flag, filter)).toBe(expected)
    })
})

describe('flagMatchesType', () => {
    const flags = {
        boolean: { ...NEW_FLAG, id: 1, key: 'bool', filters: { groups: [] } } as FeatureFlagType,
        multivariant: {
            ...NEW_FLAG,
            id: 2,
            key: 'multi',
            filters: { groups: [], multivariate: { variants: [{ key: 'a', rollout_percentage: 100 }] } },
        } as FeatureFlagType,
        experiment: { ...NEW_FLAG, id: 3, key: 'exp', experiment_set: [1] } as FeatureFlagType,
        remote_config: { ...NEW_FLAG, id: 4, key: 'remote', is_remote_configuration: true } as FeatureFlagType,
    }

    it.each<[keyof typeof flags, string | undefined, boolean]>([
        ['boolean', undefined, true],
        ['boolean', 'boolean', true],
        ['boolean', 'multivariant', false],
        ['multivariant', 'multivariant', true],
        ['experiment', 'experiment', true],
        ['remote_config', 'remote_config', true],
    ])('%s with type=%p → %p', (flagKey, type, expected) => {
        expect(flagMatchesType(flags[flagKey], type)).toBe(expected)
    })
})

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
})

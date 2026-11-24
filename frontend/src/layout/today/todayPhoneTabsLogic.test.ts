import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import { todayPhoneTabsLogic } from './todayPhoneTabsLogic'

describe('todayPhoneTabsLogic', () => {
    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
    })

    test.each([
        ['no change', [], ['home', 'analytics', 'products'], ['spaces', 'people']],
        ['a swap', ['products', 'people'], ['home', 'analytics', 'people'], ['spaces', 'products']],
        ['an add past the limit', ['spaces'], ['home', 'analytics', 'products'], ['spaces', 'people']],
        [
            'a removal of the last tab',
            ['analytics', 'products', 'home'],
            ['home'],
            ['spaces', 'analytics', 'people', 'products'],
        ],
    ] as const)('after %s, the tab bar keeps its limit and More lists the other areas', (_, toggles, tabs, more) => {
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.TODAY_RAIL_NAV], {
            [FEATURE_FLAGS.TODAY_RAIL_NAV]: true,
        })
        const logic = todayPhoneTabsLogic()
        logic.mount()

        toggles.forEach((pane) => logic.actions.togglePhoneTab(pane))

        expect(logic.values.phoneTabPanes).toEqual(tabs)
        expect(logic.values.phoneMorePanes).toEqual(more)
    })

    it('drops a tab whose area flag turns off, and resets to the default tabs', () => {
        const flags = { [FEATURE_FLAGS.TODAY_RAIL_NAV]: true, [FEATURE_FLAGS.MONITOR_AREA]: true }
        featureFlagLogic.actions.setFeatureFlags(Object.keys(flags), flags)
        const logic = todayPhoneTabsLogic()
        logic.mount()

        logic.actions.togglePhoneTab('products')
        logic.actions.togglePhoneTab('monitor')
        expect(logic.values.phoneTabPanes).toEqual(['home', 'analytics', 'monitor'])

        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.TODAY_RAIL_NAV], {
            [FEATURE_FLAGS.TODAY_RAIL_NAV]: true,
        })
        expect(logic.values.phoneTabPanes).toEqual(['home', 'analytics'])

        logic.actions.resetPhoneTabs()
        expect(logic.values.phoneTabPanes).toEqual(['home', 'analytics', 'products'])
    })
})

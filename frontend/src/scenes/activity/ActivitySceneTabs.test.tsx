import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { Provider } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'
import { ActivityTab } from '~/types'

import { ActivitySceneTabs } from './ActivitySceneTabs'
import { ActivitySceneTabKey } from './activitySceneTabsLogic'

describe('ActivitySceneTabs', () => {
    beforeEach(() => {
        initKeaTests()
        featureFlagLogic.mount()
    })

    afterEach(() => {
        cleanup()
    })

    test.each([
        // The People pane links to Persons, so its page has no tabs.
        ['persons', true, false],
        [ActivityTab.ExploreEvents, true, true],
        ['persons', false, true],
        [ActivityTab.ExploreEvents, false, true],
    ] as [ActivitySceneTabKey, boolean, boolean][])(
        'with key %s and today-rail-nav %s, shows the tabs: %s',
        (activeKey, todayRailNav, shown) => {
            featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.TODAY_RAIL_NAV], {
                [FEATURE_FLAGS.TODAY_RAIL_NAV]: todayRailNav,
            })

            render(
                <Provider>
                    <ActivitySceneTabs activeKey={activeKey} />
                </Provider>
            )

            expect(screen.queryAllByRole('tab').length > 0).toBe(shown)
        }
    )
})

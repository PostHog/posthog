import { initKeaTests } from '~/test/init'
import { ActivityTab } from '~/types'

import { ActivitySceneTabKey, activitySceneTabsLogic } from './activitySceneTabsLogic'

describe('activitySceneTabsLogic', () => {
    beforeEach(() => {
        initKeaTests()
        activitySceneTabsLogic.mount()
    })

    it.each<ActivitySceneTabKey>([
        ActivityTab.ExploreEvents,
        ActivityTab.LiveEvents,
        ActivityTab.ExploreSessions,
        'persons',
        'cohorts',
        'groups-0',
    ])('keeps activity and people navigation separate on %s', (activeKey) => {
        const activityKeys = [ActivityTab.ExploreEvents, ActivityTab.LiveEvents, ActivityTab.ExploreSessions]
        const expected = activityKeys.includes(activeKey as ActivityTab)
            ? activityKeys
            : ['persons', 'cohorts', 'groups-0']

        expect(activitySceneTabsLogic.values.tabsForKey(activeKey).map((tab) => tab.key)).toEqual(expected)
    })
})

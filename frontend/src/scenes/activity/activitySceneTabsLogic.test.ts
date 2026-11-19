import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { teamLogic } from 'scenes/teamLogic'

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

    it.each([
        [
            true,
            [
                ActivityTab.ExploreEvents,
                ActivityTab.LiveEvents,
                ActivityTab.ExploreSessions,
                ActivityTab.ExploreFlagCalls,
            ],
        ],
        [false, [ActivityTab.ExploreEvents, ActivityTab.LiveEvents, ActivityTab.ExploreSessions]],
    ])(
        'shows the flag calls tab when flag calls are only in flag_evaluations is %s',
        (onlyInFlagEvaluations, expected) => {
            teamLogic.actions.loadCurrentTeamSuccess({
                ...MOCK_DEFAULT_TEAM,
                flag_calls_only_in_flag_evaluations: onlyInFlagEvaluations,
            })

            expect(activitySceneTabsLogic.values.tabsForKey(ActivityTab.ExploreEvents).map((tab) => tab.key)).toEqual(
                expected
            )
        }
    )
})

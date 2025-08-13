import { actions, kea, path, reducers, selectors } from 'kea'
import type { activitySceneLogicType } from 'scenes/activity/ActivitySceneType'
import { tabAwareScene } from 'lib/logic/scene-plugin/tabAwareScene'
import { ActivityTab, Breadcrumb } from '~/types'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { capitalizeFirstLetter } from 'lib/utils'
import { tabAwareUrlToAction } from 'lib/logic/scene-plugin/tabAwareUrlToAction'

export const activitySceneLogic = kea<activitySceneLogicType>([
    path(['scenes', 'events', 'activitySceneLogic']),
    tabAwareScene(),
    actions({
        setTab: (tab: ActivityTab) => ({ tab }),
    }),
    reducers({
        tab: [
            ActivityTab.ExploreEvents as ActivityTab,
            {
                setTab: (_, { tab }) => tab,
            },
        ],
    }),
    selectors({
        breadcrumbs: [
            (s) => [s.tab],
            (tab): Breadcrumb[] => [
                {
                    key: Scene.Activity,
                    name: `Activity`,
                    path: urls.activity(),
                },
                {
                    key: tab,
                    name: capitalizeFirstLetter(tab),
                },
            ],
        ],
        tabId: [() => [(_, props) => props.tabId], (tabId): string => tabId],
    }),
    tabAwareUrlToAction(({ actions }) => ({
        [urls.activity(':tab')]: ({ tab }) => {
            actions.setTab(tab as ActivityTab)
        },
    })),
])

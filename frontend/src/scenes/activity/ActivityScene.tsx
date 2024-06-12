import { actions, connect, kea, path, reducers, selectors, useActions, useValues } from 'kea'
import { urlToAction } from 'kea-router'
import { PageHeader } from 'lib/components/PageHeader'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonTab, LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { capitalizeFirstLetter } from 'lib/utils'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { ActivityTab, Breadcrumb } from '~/types'

import type { activitySceneLogicType } from './ActivitySceneType'
import { EventsScene } from './explore/EventsScene'
import { LiveEventsTable } from './live/LiveEventsTable'

const ACTIVITY_TABS: LemonTab<ActivityTab>[] = [
    {
        key: ActivityTab.ExploreEvents,
        label: 'Explore',
        content: <EventsScene />,
        link: urls.activity(ActivityTab.ExploreEvents),
    },
    {
        key: ActivityTab.LiveEvents,
        label: 'Live',
        content: <LiveEventsTable />,
        link: urls.activity(ActivityTab.LiveEvents),
    },
]

const activitySceneLogic = kea<activitySceneLogicType>([
    path(['scenes', 'events', 'activitySceneLogic']),
    connect({
        values: [featureFlagLogic, ['featureFlags']],
    }),
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
            (s) => [s.tab, s.featureFlags],
            (tab, featureFlags): Breadcrumb[] =>
                featureFlags[FEATURE_FLAGS.LIVE_EVENTS]
                    ? // Explore and Live as separate tabs
                      [
                          {
                              key: Scene.Activity,
                              name: `Activity`,
                              path: urls.activity(),
                          },
                          {
                              key: tab,
                              name: capitalizeFirstLetter(tab),
                          },
                      ]
                    : // There's no Live, so no tabs to worry about
                      [
                          {
                              key: Scene.Activity,
                              name: `Activity`,
                          },
                      ],
        ],
    }),
    urlToAction(({ actions }) => ({
        [urls.activity(':tab')]: ({ tab }) => {
            actions.setTab(tab as ActivityTab)
        },
    })),
])

export function ActivityScene(): JSX.Element {
    const { tab } = useValues(activitySceneLogic)
    const { setTab } = useActions(activitySceneLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    return (
        <>
            <PageHeader tabbedPage />
            {featureFlags[FEATURE_FLAGS.LIVE_EVENTS] ? (
                <LemonTabs activeKey={tab} onChange={(t) => setTab(t)} tabs={ACTIVITY_TABS} />
            ) : (
                <EventsScene />
            )}
        </>
    )
}

export const scene: SceneExport = {
    component: ActivityScene,
    logic: activitySceneLogic,
}

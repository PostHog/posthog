import { actions, connect, kea, path, reducers, selectors, useActions, useValues } from 'kea'
import { actionToUrl, combineUrl, router, urlToAction } from 'kea-router'
import { PageHeader } from 'lib/components/PageHeader'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonTab, LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { capitalizeFirstLetter } from 'lib/utils'
import React from 'react'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import type { activitySceneLogicType } from './ActivitySceneType'
import { EventsScene } from './events/EventsScene'
import { LiveEventsTable } from './live-events/LiveEventsTable'

export enum ActivityTab {
    ExploreEvents = 'explore',
    LiveEvents = 'live',
}

const tabs: Record<
    ActivityTab,
    { url: string; label: LemonTab<any>['label']; content: JSX.Element; buttons?: React.ReactNode }
> = {
    [ActivityTab.ExploreEvents]: {
        url: urls.exploreEvents(),
        label: 'Explore',
        content: <EventsScene />,
    },
    [ActivityTab.LiveEvents]: {
        url: urls.liveEvents(),
        label: 'Live',
        content: <LiveEventsTable />,
    },
}

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
            (s) => [s.tab],
            (tab): Breadcrumb[] => {
                return [
                    {
                        key: Scene.Activity,
                        name: `Activity`,
                        path: tabs.explore.url,
                    },
                    {
                        key: tab,
                        name: capitalizeFirstLetter(tab),
                        path: tabs[tab].url,
                    },
                ]
            },
        ],
        enabledTabs: [
            () => [],
            (): ActivityTab[] => {
                return Object.keys(tabs) as ActivityTab[]
            },
        ],
    }),
    actionToUrl(() => ({
        setTab: ({ tab }) => {
            const tabUrl = tabs[tab as ActivityTab]?.url || tabs.explore.url
            if (combineUrl(tabUrl).pathname === router.values.location.pathname) {
                // don't clear the parameters if we're already on the right page
                // otherwise we can't use a url with parameters as a landing page
                return
            }
            return tabUrl
        },
    })),
    urlToAction(({ actions, values }) => {
        return Object.fromEntries(
            Object.entries(tabs).map(([key, tab]) => [
                tab.url,
                () => {
                    if (values.tab !== key) {
                        actions.setTab(key as ActivityTab)
                    }
                },
            ])
        )
    }),
])

export function ActivityScene(): JSX.Element {
    const { tab, enabledTabs } = useValues(activitySceneLogic)
    const { setTab } = useActions(activitySceneLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const lemonTabs: LemonTab<ActivityTab>[] = enabledTabs.map((key) => ({
        key: key as ActivityTab,
        label: <span data-attr={`activity-${key}-tab`}>{tabs[key].label}</span>,
        content: tabs[key].content,
    }))

    return (
        <>
            <PageHeader tabbedPage buttons={<>{tabs[tab].buttons}</>} />

            {featureFlags[FEATURE_FLAGS.LIVE_EVENTS] ? (
                <LemonTabs activeKey={tab} onChange={(t) => setTab(t)} tabs={lemonTabs} />
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

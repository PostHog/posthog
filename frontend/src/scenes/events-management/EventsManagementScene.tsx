import { actions, connect, kea, path, reducers, selectors, useActions, useValues } from 'kea'
import { actionToUrl, combineUrl, router, urlToAction } from 'kea-router'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonTab, LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { capitalizeFirstLetter } from 'lib/utils'
import React from 'react'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import type { eventsManagementSceneLogicType } from './EventsManagementSceneType'
import { EventsScene } from './events/EventsScene'
import { LiveEventsScene } from './live-events/LiveEventsScene'

export enum EventsManagementTab {
    Events = 'events',
    LiveEvents = 'live',
}

const tabs: Record<
    EventsManagementTab,
    { url: string; label: LemonTab<any>['label']; content: JSX.Element; buttons?: React.ReactNode }
> = {
    [EventsManagementTab.Events]: {
        url: urls.events(),
        label: 'Events',
        content: <EventsScene />,
    },
    [EventsManagementTab.LiveEvents]: {
        url: urls.liveEvents(),
        label: 'Live Events',
        content: <LiveEventsScene />,
    },
}

const eventsManagementSceneLogic = kea<eventsManagementSceneLogicType>([
    path(['scenes', 'events', 'eventsManagementSceneLogic']),
    connect({
        values: [featureFlagLogic, ['featureFlags']],
    }),
    actions({
        setTab: (tab: EventsManagementTab) => ({ tab }),
    }),
    reducers({
        tab: [
            EventsManagementTab.Events as EventsManagementTab,
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
                        key: Scene.EventsManagement,
                        name: `Activity`,
                        path: tabs.events.url,
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
            (): EventsManagementTab[] => {
                return Object.keys(tabs) as EventsManagementTab[]
            },
        ],
    }),
    actionToUrl(() => ({
        setTab: ({ tab }) => {
            const tabUrl = tabs[tab as EventsManagementTab]?.url || tabs.events.url
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
                        actions.setTab(key as EventsManagementTab)
                    }
                },
            ])
        )
    }),
])

export function EventsManagementScene(): JSX.Element {
    const { tab, enabledTabs } = useValues(eventsManagementSceneLogic)
    const { setTab } = useActions(eventsManagementSceneLogic)

    console.log('tabs', tabs)
    const lemonTabs: LemonTab<EventsManagementTab>[] = enabledTabs.map((key) => ({
        key: key as EventsManagementTab,
        label: <span data-attr={`events-management-${key}-tab`}>{tabs[key].label}</span>,
        content: tabs[key].content,
    }))

    return (
        <>
            <PageHeader
                caption="Monitor your events with live event streams, and filtering of events."
                tabbedPage
                buttons={<>{tabs[tab].buttons}</>}
            />

            <LemonTabs activeKey={tab} onChange={(t) => setTab(t)} tabs={lemonTabs} />
        </>
    )
}

export const scene: SceneExport = {
    component: EventsManagementScene,
    logic: eventsManagementSceneLogic,
}

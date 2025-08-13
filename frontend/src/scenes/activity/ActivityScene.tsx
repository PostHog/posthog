import { useActions, useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { ActivityTab } from '~/types'

import { EventsScene } from './explore/EventsScene'
import { LiveEventsTable } from './live/LiveEventsTable'
import { activitySceneLogic } from 'scenes/activity/activitySceneLogic'

export function ActivityScene(): JSX.Element {
    const { tab, tabId } = useValues(activitySceneLogic)
    const { setTab } = useActions(activitySceneLogic)

    return (
        <>
            <PageHeader tabbedPage />
            <LemonTabs
                activeKey={tab}
                onChange={(t) => setTab(t)}
                tabs={[
                    {
                        key: ActivityTab.ExploreEvents,
                        label: 'Explore',
                        content: <EventsScene tabId={tabId} />,
                        link: urls.activity(ActivityTab.ExploreEvents),
                    },
                    {
                        key: ActivityTab.LiveEvents,
                        label: 'Live',
                        content: <LiveEventsTable tabId={tabId} />,
                        link: urls.activity(ActivityTab.LiveEvents),
                    },
                ]}
            />
        </>
    )
}

export const scene: SceneExport = {
    component: ActivityScene,
    logic: activitySceneLogic,
    settingSectionId: 'environment-autocapture',
}

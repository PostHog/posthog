import { useActions, useValues } from 'kea'

import { QueryFeature } from '~/queries/nodes/DataTable/queryFeatures'
import { Query } from '~/queries/Query/Query'

import { eventsSceneLogic } from './eventsSceneLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { ActivityTab } from '~/types'
import { urls } from 'scenes/urls'
import { IconApps } from '@posthog/icons'
import { SceneContent, SceneDivider, SceneTitleSection } from '~/layout/scenes/SceneContent'
const RESOURCE_TYPE = 'event'

export function EventsScene({ tabId }: { tabId?: string } = {}): JSX.Element {
    const { query } = useValues(eventsSceneLogic)
    const { setQuery } = useActions(eventsSceneLogic)

    return (
        <SceneContent>
            <PageHeader tabbedPage />
            <SceneTitleSection
                name="Explore events"
                description="A catalog of all user interactions with your app or website."
                resourceType={{
                    type: RESOURCE_TYPE,
                    typePlural: 'events',
                    forceIcon: <IconApps />,
                }}
            />
            <SceneDivider />
            <LemonTabs
                activeKey={ActivityTab.ExploreEvents}
                tabs={[
                    {
                        key: ActivityTab.ExploreEvents,
                        label: 'Explore',
                        link: urls.activity(ActivityTab.ExploreEvents),
                    },
                    {
                        key: ActivityTab.LiveEvents,
                        label: 'Live',
                        link: urls.activity(ActivityTab.LiveEvents),
                    },
                ]}
            />
            <Query
                attachTo={eventsSceneLogic({ tabId })}
                uniqueKey={`events-scene-${tabId}`}
                query={query}
                setQuery={setQuery}
                context={{
                    showOpenEditorButton: true,
                    extraDataTableQueryFeatures: [QueryFeature.highlightExceptionEventRows],
                }}
            />
        </SceneContent>
    )
}

export const scene: SceneExport = {
    component: EventsScene,
    logic: eventsSceneLogic,
    settingSectionId: 'environment-autocapture',
}

import { useActions, useValues } from 'kea'

import { IconApps } from '@posthog/icons'

import { PageHeader } from 'lib/components/PageHeader'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { Query } from '~/queries/Query/Query'
import { QueryFeature } from '~/queries/nodes/DataTable/queryFeatures'
import { ActivityTab } from '~/types'

import { eventsSceneLogic } from './eventsSceneLogic'

const RESOURCE_TYPE = 'event'

export function EventsScene({ tabId }: { tabId?: string } = {}): JSX.Element {
    const { query } = useValues(eventsSceneLogic)
    const { setQuery } = useActions(eventsSceneLogic)
    const newSceneLayout = useFeatureFlag('NEW_SCENE_LAYOUT')

    return (
        <SceneContent>
            <PageHeader tabbedPage />
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
                sceneInset={newSceneLayout}
            />
            <SceneTitleSection
                name="Explore events"
                description="A catalog of all user interactions with your app or website."
                resourceType={{
                    type: RESOURCE_TYPE,
                    forceIcon: <IconApps />,
                }}
            />
            <SceneDivider />
            <Query
                attachTo={eventsSceneLogic({ tabId })}
                uniqueKey={`events-scene-${tabId}`}
                query={query}
                setQuery={setQuery}
                context={{
                    showOpenEditorButton: true,
                    extraDataTableQueryFeatures: [QueryFeature.highlightExceptionEventRows],
                    dataTableMaxPaginationLimit: 200,
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

import { useActions, useValues } from 'kea'

import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { Query } from '~/queries/Query/Query'
import { QueryFeature } from '~/queries/nodes/DataTable/queryFeatures'
import { ActivityTab } from '~/types'

import { eventsSceneLogic } from './eventsSceneLogic'

export function EventsScene({ tabId }: { tabId?: string } = {}): JSX.Element {
    const { query } = useValues(eventsSceneLogic)
    const { setQuery } = useActions(eventsSceneLogic)

    return (
        <SceneContent>
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
                sceneInset
            />
            <SceneTitleSection
                name={sceneConfigurations[Scene.ExploreEvents].name}
                description={sceneConfigurations[Scene.ExploreEvents].description}
                resourceType={{
                    type: sceneConfigurations[Scene.ExploreEvents].iconType || 'default_icon_type',
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

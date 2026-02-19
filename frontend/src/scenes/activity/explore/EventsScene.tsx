import { useActions, useValues } from 'kea'

import { ActivitySceneTabs } from 'scenes/activity/ActivitySceneTabs'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { Query } from '~/queries/Query/Query'
import { QueryFeature } from '~/queries/nodes/DataTable/queryFeatures'
import { ProductKey } from '~/queries/schema/schema-general'
import { ActivityTab } from '~/types'

import { eventsSceneLogic } from './eventsSceneLogic'

export function EventsScene({ tabId }: { tabId?: string } = {}): JSX.Element {
    const { query } = useValues(eventsSceneLogic)
    const { setQuery } = useActions(eventsSceneLogic)

    return (
        <SceneContent>
            <ActivitySceneTabs activeKey={ActivityTab.ExploreEvents} />
            <SceneTitleSection
                name={sceneConfigurations[Scene.Activity].name}
                description={sceneConfigurations[Scene.Activity].description}
                resourceType={{
                    type: sceneConfigurations[Scene.ExploreEvents].iconType || 'default_icon_type',
                }}
            />
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
    productKey: ProductKey.PRODUCT_ANALYTICS,
}

import { useActions, useValues } from 'kea'

import { ActivitySceneTabs } from 'scenes/activity/ActivitySceneTabs'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene, SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { QueryFeature } from '~/queries/nodes/DataTable/queryFeatures'
import { Query } from '~/queries/Query/Query'
import { ProductKey } from '~/queries/schema/schema-general'
import { ActivityTab } from '~/types'

import { eventsSceneLogic } from './eventsSceneLogic'
import { getExploreEmptyStateContext } from './exploreEmptyState'

export function EventsScene(): JSX.Element {
    const { query } = useValues(eventsSceneLogic())
    const { setQuery } = useActions(eventsSceneLogic())

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
                attachTo={eventsSceneLogic()}
                uniqueKey="events-scene"
                query={query}
                setQuery={setQuery}
                context={{
                    showOpenEditorButton: true,
                    extraDataTableQueryFeatures: [QueryFeature.highlightExceptionEventRows],
                    dataTableMaxPaginationLimit: 200,
                    ...getExploreEmptyStateContext(query, setQuery),
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

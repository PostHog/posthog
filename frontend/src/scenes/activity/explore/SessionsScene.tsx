import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { ActivitySceneTabs } from 'scenes/activity/ActivitySceneTabs'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { Query } from '~/queries/Query/Query'
import { QueryFeature } from '~/queries/nodes/DataTable/queryFeatures'
import { DataTableNode, ProductKey } from '~/queries/schema/schema-general'
import { ActivityTab } from '~/types'

import { createSessionsRowTransformer, getSessionsColumns } from './sessionsColumns'
import { sessionsSceneLogic } from './sessionsSceneLogic'

export function SessionsScene({ tabId }: { tabId?: string } = {}): JSX.Element {
    const { query } = useValues(sessionsSceneLogic)
    const { setQuery } = useActions(sessionsSceneLogic)

    // Create the row transformer based on the current query
    const dataTableRowsTransformer = useMemo(() => createSessionsRowTransformer(query as DataTableNode), [query])

    return (
        <SceneContent>
            <ActivitySceneTabs activeKey={ActivityTab.ExploreSessions} />
            <SceneTitleSection
                name={sceneConfigurations[Scene.ExploreSessions].name}
                description={sceneConfigurations[Scene.ExploreSessions].description}
                resourceType={{
                    type: sceneConfigurations[Scene.ExploreSessions].iconType || 'default_icon_type',
                }}
            />
            <Query
                attachTo={sessionsSceneLogic({ tabId })}
                uniqueKey={`sessions-scene-${tabId}`}
                query={query}
                setQuery={setQuery}
                context={{
                    columns: getSessionsColumns(),
                    showOpenEditorButton: true,
                    extraDataTableQueryFeatures: [QueryFeature.highlightExceptionEventRows],
                    dataTableMaxPaginationLimit: 200,
                    dataTableRowsTransformer,
                }}
            />
        </SceneContent>
    )
}

export const scene: SceneExport = {
    component: SessionsScene,
    logic: sessionsSceneLogic,
    productKey: ProductKey.PRODUCT_ANALYTICS,
}

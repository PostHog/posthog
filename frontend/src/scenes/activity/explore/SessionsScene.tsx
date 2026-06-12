import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { QueryFeature } from '@posthog/query-frontend/nodes/DataTable/queryFeatures'
import { Query } from '@posthog/query-frontend/Query/Query'
import { DataTableNode, ProductKey } from '@posthog/query-frontend/schema/schema-general'

import { ActivitySceneTabs } from 'scenes/activity/ActivitySceneTabs'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene, SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ActivityTab } from '~/types'

import { createSessionsRowTransformer, getSessionsColumns } from './sessionsColumns'
import { sessionsSceneLogic } from './sessionsSceneLogic'

export function SessionsScene(): JSX.Element {
    const { query } = useValues(sessionsSceneLogic())
    const { setQuery } = useActions(sessionsSceneLogic())

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
                attachTo={sessionsSceneLogic()}
                uniqueKey="sessions-scene"
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

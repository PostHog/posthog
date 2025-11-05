import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { Query } from '~/queries/Query/Query'
import { QueryFeature } from '~/queries/nodes/DataTable/queryFeatures'
import { DataTableNode } from '~/queries/schema/schema-general'
import { ActivityTab } from '~/types'

import { createSessionsRowTransformer, getSessionsColumns } from './sessionsColumns'
import { sessionsSceneLogic } from './sessionsSceneLogic'
import { useActivityTabs } from './utils'

export function SessionsScene({ tabId }: { tabId?: string } = {}): JSX.Element {
    const { query } = useValues(sessionsSceneLogic)
    const { setQuery } = useActions(sessionsSceneLogic)
    const tabs = useActivityTabs()

    // Create the row transformer based on the current query
    const dataTableRowsTransformer = useMemo(() => createSessionsRowTransformer(query as DataTableNode), [query])

    return (
        <SceneContent>
            <LemonTabs activeKey={ActivityTab.ExploreSessions} tabs={tabs} sceneInset />
            <SceneTitleSection
                name={sceneConfigurations[Scene.ExploreSessions].name}
                description={sceneConfigurations[Scene.ExploreSessions].description}
                resourceType={{
                    type: sceneConfigurations[Scene.ExploreSessions].iconType || 'default_icon_type',
                }}
            />
            <SceneDivider />
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
}

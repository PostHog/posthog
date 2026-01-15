import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { Query } from '~/queries/Query/Query'
import { QueryFeature } from '~/queries/nodes/DataTable/queryFeatures'
import { ActivityTab } from '~/types'

import { eventsSceneLogic } from './eventsSceneLogic'
import { useActivityTabs } from './utils'

export function EventsScene({ tabId }: { tabId?: string } = {}): JSX.Element {
    const { query, expandedRowIndices } = useValues(eventsSceneLogic)
    const { setQuery, toggleRowExpanded } = useActions(eventsSceneLogic)
    const tabs = useActivityTabs()

    const expandableConfig = useMemo(
        () => ({
            isRowExpanded: (_record: unknown, recordIndex: number): number =>
                expandedRowIndices.has(recordIndex) ? 1 : 0,
            onRowExpand: (_record: unknown, recordIndex: number): void => {
                toggleRowExpanded(recordIndex)
            },
            onRowCollapse: (_record: unknown, recordIndex: number): void => {
                toggleRowExpanded(recordIndex)
            },
        }),
        [expandedRowIndices, toggleRowExpanded]
    )

    return (
        <SceneContent>
            <LemonTabs activeKey={ActivityTab.ExploreEvents} tabs={tabs} sceneInset className="mb-3" />
            <SceneTitleSection
                name={sceneConfigurations[Scene.Activity].name}
                description={sceneConfigurations[Scene.Activity].description}
                resourceType={{
                    type: sceneConfigurations[Scene.Activity].iconType || 'default_icon_type',
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
                    expandable: expandableConfig,
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

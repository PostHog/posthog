import { startCustomerJourney } from 'lib/customerJourneys/startCustomerJourney'
import { uuid } from 'lib/utils/dom'
import { SQLEditorMode } from 'scenes/data-warehouse/editor/sqlEditorModes'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'

import { QueryJourneyDescriptor } from '~/queries/nodes/DataNode/queryJourney'

export function createSqlQueryJourney(
    tabId: string,
    mode: SQLEditorMode | undefined
): QueryJourneyDescriptor | undefined {
    if ((mode ?? SQLEditorMode.FullScene) !== SQLEditorMode.FullScene) {
        return undefined
    }
    const resourceId = uuid()
    return {
        requireObservedSurface: true,
        startRequest: (queryId) => {
            const scene = sceneLogic.findMounted()?.values
            if (
                scene?.activeSceneId !== Scene.SQLEditor ||
                (scene.activeSceneComponentParams.tabId ?? 'default') !== tabId
            ) {
                return null
            }
            return startCustomerJourney({
                journey_name: 'sql_run',
                resource_type: 'sql_editor',
                resource_id: resourceId,
                trigger: 'query_execution',
                readiness_scope: 'sql_query_to_results_commit',
                readiness_contract_version: 1,
                attempt_id: queryId,
                client_query_id: queryId,
            })
        },
    }
}

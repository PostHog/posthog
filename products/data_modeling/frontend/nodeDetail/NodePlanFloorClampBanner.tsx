import { useValues } from 'kea'

import { materializationJobsLogic } from 'scenes/data-warehouse/saved_queries/materializationJobsLogic'
import { PlanFloorClampBanner } from 'scenes/data-warehouse/saved_queries/PlanFloorClampBanner'

import { nodeDetailSceneLogic } from './nodeDetailSceneLogic'

export function NodePlanFloorClampBanner({ id }: { id: string }): JSX.Element | null {
    const { node, savedQuery: initialSavedQuery } = useValues(nodeDetailSceneLogic({ id }))
    const subject = node?.type === 'endpoint' ? 'endpoint' : 'view'
    const { savedQuery: currentSavedQuery } = useValues(
        materializationJobsLogic({ viewId: node?.saved_query_id ?? '', kind: subject })
    )
    const savedQuery = currentSavedQuery ?? initialSavedQuery

    if (!savedQuery?.plan_clamp) {
        return null
    }

    return (
        <PlanFloorClampBanner
            subject={subject}
            subjectId={savedQuery.id}
            previousSeconds={savedQuery.plan_clamp.previous_target_seconds}
            planFloorSeconds={savedQuery.plan_clamp.plan_floor_seconds}
            at={savedQuery.plan_clamp.at}
        />
    )
}

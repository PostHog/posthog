import { useValues } from 'kea'
import { NotFound } from 'lib/components/NotFound'
import { Insight } from 'scenes/insights/Insight'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'
import { InsightSkeleton } from 'scenes/insights/InsightSkeleton'
import { SceneExport } from 'scenes/sceneTypes'

export function InsightScene(): JSX.Element {
    const { insightId, insight, insightLogicRef } = useValues(insightSceneLogic)

    if (insightId === 'new' || (insightId && insight?.id && insight?.short_id)) {
        return <Insight insightId={insightId} />
    }

    if (insightLogicRef?.logic?.values?.insightLoading) {
        return <InsightSkeleton />
    }

    return <NotFound object="insight" />
}

export const scene: SceneExport = {
    component: InsightScene,
    logic: insightSceneLogic,
}

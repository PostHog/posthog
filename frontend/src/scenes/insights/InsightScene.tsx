import { SceneExport } from 'scenes/sceneTypes'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'
import { useValues } from 'kea'
import { Insight } from 'scenes/insights/Insight'
import { InsightSkeleton } from 'scenes/insights/InsightSkeleton'
import { NotFound } from 'lib/components/NotFound'

export function InsightScene(): JSX.Element {
    const { insightId, insight, insightCache } = useValues(insightSceneLogic)

    if (insightId === 'new' || (insightId && insight?.id && insight?.short_id)) {
        console.log('saved insight: loading scene for insight', insight)
        return <Insight insightId={insightId} />
    }

    if (insightCache?.logic?.values?.insightLoading) {
        return <InsightSkeleton />
    }

    return <NotFound object={'insight'} />
}

export const scene: SceneExport = {
    component: InsightScene,
    logic: insightSceneLogic,
}

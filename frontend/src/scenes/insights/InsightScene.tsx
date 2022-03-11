import React from 'react'
import { SceneExport } from 'scenes/sceneTypes'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'
import { useValues } from 'kea'
import { Insight } from 'scenes/insights/Insight'
import { InsightSkeleton } from 'scenes/insights/InsightSkeleton'

export function InsightScene(): JSX.Element {
    const { insightId, insight } = useValues(insightSceneLogic)

    if (insightId && insightId !== 'new' && insight && insight.short_id && insight.id) {
        return <Insight insightId={insightId} />
    }

    return <InsightSkeleton />
}

export const scene: SceneExport = {
    component: InsightScene,
    logic: insightSceneLogic,
}

import { useValues } from 'kea'
import { router } from 'kea-router'
import { NotFound } from 'lib/components/NotFound'
import { useEffect } from 'react'
import { Insight } from 'scenes/insights/Insight'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'
import { InsightSkeleton } from 'scenes/insights/InsightSkeleton'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { NodeKind } from '~/queries/schema/schema-general'
import { ItemMode } from '~/types'

export function InsightScene(): JSX.Element {
    const { insightId, insight, insightLogicRef, insightMode } = useValues(insightSceneLogic)

    useEffect(() => {
        // Redirect data viz nodes to the sql editor
        if (insightId && insight?.query?.kind === NodeKind.DataVisualizationNode && insightMode === ItemMode.Edit) {
            router.actions.push(urls.sqlEditor(undefined, undefined, insightId))
        }
    }, [insightId, insight?.query?.kind, insightMode])

    if (
        insightId === 'new' ||
        (insightId &&
            insight?.id &&
            insight?.short_id &&
            (insight?.query?.kind !== NodeKind.DataVisualizationNode || insightMode !== ItemMode.Edit))
    ) {
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

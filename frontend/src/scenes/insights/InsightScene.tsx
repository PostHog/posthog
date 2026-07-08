import { useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect } from 'react'

import { NotFound } from 'lib/components/NotFound'
import { InsightAsScene } from 'scenes/insights/InsightAsScene'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'
import { InsightSkeleton } from 'scenes/insights/InsightSkeleton'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { NodeKind, ProductKey } from '~/queries/schema/schema-general'
import { ItemMode } from '~/types'

export function InsightScene(): JSX.Element {
    const { insightId, insight, insightLogicRef, insightMode, dashboardId } = useValues(insightSceneLogic)
    useEffect(() => {
        // Redirect data viz nodes to the sql editor
        if (insightId && insight?.query?.kind === NodeKind.DataVisualizationNode && insightMode === ItemMode.Edit) {
            router.actions.push(
                urls.sqlEditor({
                    insightShortId: insightId,
                    dashboard: dashboardId ?? undefined,
                })
            )
        }
    }, [insightId, insight?.query?.kind, insightMode, dashboardId])

    if (
        insightId === 'new' ||
        insightId?.startsWith('new-') ||
        (insightId &&
            insight?.id &&
            insight?.short_id &&
            (insight?.query?.kind !== NodeKind.DataVisualizationNode || insightMode !== ItemMode.Edit))
    ) {
        return <InsightAsScene insightId={insightId} attachTo={insightSceneLogic} />
    }

    if (insightLogicRef?.logic?.values?.insightLoading) {
        return <InsightSkeleton />
    }

    return <NotFound object="insight" />
}

export const scene: SceneExport = {
    component: InsightScene,
    logic: insightSceneLogic,
    productKey: ProductKey.PRODUCT_ANALYTICS,
}

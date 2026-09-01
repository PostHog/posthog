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

import { useAttachedContext } from 'products/posthog_ai/frontend/api/logics'

export function InsightScene(): JSX.Element {
    const { insightId, insight, insightMissing, accessDeniedToInsight, insightMode, dashboardId } =
        useValues(insightSceneLogic)

    useAttachedContext(
        insight?.short_id && insight?.query
            ? [{ type: 'insight', key: insight.short_id, label: insight.name || insight.derived_name || undefined }]
            : null
    )

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

    // Only show the not-found page once a load has actually failed. While the insight still
    // resolves, or its logic ref swaps after a save from the SQL editor, treat it as loading so
    // it does not flash a 404.
    if (insightMissing || accessDeniedToInsight) {
        return <NotFound object="insight" />
    }

    return <InsightSkeleton />
}

export const scene: SceneExport = {
    component: InsightScene,
    logic: insightSceneLogic,
    productKey: ProductKey.PRODUCT_ANALYTICS,
}

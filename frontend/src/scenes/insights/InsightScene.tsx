import { useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect } from 'react'

import { NotFound } from 'lib/components/NotFound'
import { InsightAsScene } from 'scenes/insights/InsightAsScene'
import { InsightLoadError } from 'scenes/insights/InsightLoadError'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'
import { InsightSkeleton } from 'scenes/insights/InsightSkeleton'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { NodeKind, ProductKey } from '~/queries/schema/schema-general'
import { InsightShortId, ItemMode } from '~/types'

import { useAttachedContext } from 'products/posthog_ai/frontend/api/logics'

export function InsightScene(): JSX.Element {
    const {
        insightId,
        insight,
        insightLogicRef,
        insightMode,
        dashboardId,
        insightLoading,
        insightLoadError,
        filtersOverride,
        variablesOverride,
        tileFiltersOverride,
    } = useValues(insightSceneLogic)

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

    if (insightLoading) {
        return <InsightSkeleton />
    }

    // A failed read says nothing about whether the insight exists, so "not found" would be a guess.
    if (insightLoadError) {
        return (
            <InsightLoadError
                status={insightLoadError.status}
                onRetry={() =>
                    insightLogicRef?.logic.actions.loadInsight(
                        insightId as InsightShortId,
                        filtersOverride,
                        variablesOverride,
                        tileFiltersOverride
                    )
                }
            />
        )
    }

    return <NotFound object="insight" />
}

export const scene: SceneExport = {
    component: InsightScene,
    logic: insightSceneLogic,
    productKey: ProductKey.PRODUCT_ANALYTICS,
}

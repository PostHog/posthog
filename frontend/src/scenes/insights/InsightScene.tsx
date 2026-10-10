import { useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect } from 'react'

import { NotFound } from 'lib/components/NotFound'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { InsightAsScene } from 'scenes/insights/InsightAsScene'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'
import { InsightSkeleton } from 'scenes/insights/InsightSkeleton'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'
import { isBIVisualizationNode, isDataVisualizationNode } from '~/queries/utils'
import { ItemMode } from '~/types'

import { useAttachedContext } from 'products/posthog_ai/frontend/api/logics'

export function InsightScene(): JSX.Element {
    const { insightId, insight, insightLoading, insightMode, dashboardId } = useValues(insightSceneLogic)
    const biEnabled = useFeatureFlag('SQL_EDITOR_BI_MODE')

    useAttachedContext(
        insight?.short_id && insight?.query
            ? [{ type: 'insight', key: insight.short_id, label: insight.name || insight.derived_name || undefined }]
            : null
    )

    useEffect(() => {
        if (
            insightId &&
            insightId !== 'new' &&
            isDataVisualizationNode(insight?.query) &&
            insightMode === ItemMode.Edit
        ) {
            if (isBIVisualizationNode(insight.query) && !biEnabled) {
                router.actions.replace(urls.insightView(insightId))
                return
            }
            const editorUrl = isBIVisualizationNode(insight.query) ? urls.businessIntelligence : urls.sqlEditor
            router.actions.push(
                editorUrl({
                    insightShortId: insightId,
                    dashboard: dashboardId ?? undefined,
                })
            )
        }
    }, [insightId, insight?.query, insightMode, dashboardId, biEnabled])

    if (
        insightId === 'new' ||
        insightId?.startsWith('new-') ||
        (insightId &&
            insight?.id &&
            insight?.short_id &&
            (!isDataVisualizationNode(insight.query) || insightMode !== ItemMode.Edit))
    ) {
        return <InsightAsScene insightId={insightId} attachTo={insightSceneLogic} />
    }

    if (insightLoading) {
        return <InsightSkeleton />
    }

    return <NotFound object="insight" />
}

export const scene: SceneExport = {
    component: InsightScene,
    logic: insightSceneLogic,
    productKey: ProductKey.PRODUCT_ANALYTICS,
}

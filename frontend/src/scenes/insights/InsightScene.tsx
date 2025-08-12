import { useValues, BindLogic } from 'kea'
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

export interface InsightSceneProps {
    tabId?: string
}

export function InsightScene({ tabId }: InsightSceneProps = {}): JSX.Element {
    if (!tabId) {
        throw new Error("No tabId in InsightScene's props")
    }
    const { insightId, insight, insightLogicRef, insightMode } = useValues(insightSceneLogic({ tabId }))

    useEffect(() => {
        // Redirect data viz nodes to the sql editor
        if (insightId && insight?.query?.kind === NodeKind.DataVisualizationNode && insightMode === ItemMode.Edit) {
            router.actions.push(urls.sqlEditor(undefined, undefined, insightId))
        }
    }, [insightId, insight?.query?.kind, insightMode])

    if (
        insightId === 'new' ||
        insightId?.startsWith('new-') ||
        (insightId &&
            insight?.id &&
            insight?.short_id &&
            (insight?.query?.kind !== NodeKind.DataVisualizationNode || insightMode !== ItemMode.Edit))
    ) {
        return (
            <BindLogic logic={insightSceneLogic} props={{ tabId }}>
                <Insight insightId={insightId} tabId={tabId} />
            </BindLogic>
        )
    }

    if (insightLogicRef?.logic?.values?.insightLoading) {
        return (
            <BindLogic logic={insightSceneLogic} props={{ tabId }}>
                <InsightSkeleton />
            </BindLogic>
        )
    }

    return (
        <BindLogic logic={insightSceneLogic} props={{ tabId }}>
            <NotFound object="insight" />
        </BindLogic>
    )
}

export const scene: SceneExport = {
    component: InsightScene,
    logic: insightSceneLogic,
    settingSectionId: 'environment-product-analytics',
}

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
import { CORE_FILTER_DEFINITIONS_BY_GROUP as NEW_TAXONOMY } from '@posthog/taxonomy'
import { CORE_FILTER_DEFINITIONS_BY_GROUP as LEGACY_TAXONOMY } from '~/lib/taxonomy'

export function InsightSceneTmp(): JSX.Element {
    return (
        <>
            <pre>{JSON.stringify(NEW_TAXONOMY, null, 2)}</pre>
            <pre>{JSON.stringify(LEGACY_TAXONOMY, null, 2)}</pre>
        </>
    )
}

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
    component: InsightSceneTmp,
    logic: insightSceneLogic,
}

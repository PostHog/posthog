import { useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect } from 'react'

import { NotFound } from 'lib/components/NotFound'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { EditorScene } from 'scenes/data-warehouse/editor/EditorScene'
import { InsightAsScene } from 'scenes/insights/InsightAsScene'
import { InsightSkeleton } from 'scenes/insights/InsightSkeleton'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { NodeKind } from '~/queries/schema/schema-general'
import { ItemMode } from '~/types'

export interface InsightSceneProps {
    tabId?: string
}

export function InsightScene({ tabId }: InsightSceneProps = {}): JSX.Element {
    if (!tabId) {
        throw new Error('<InsightScene /> must receive a tabId prop')
    }
    const { featureFlags } = useValues(featureFlagLogic)
    const { insightId, insight, insightLogicRef, insightMode } = useValues(insightSceneLogic({ tabId }))
    useEffect(() => {
        // Redirect data viz nodes to the sql editor
        if (
            !featureFlags[FEATURE_FLAGS.SCENE_TABS] &&
            insightId &&
            insight?.query?.kind === NodeKind.DataVisualizationNode &&
            insightMode === ItemMode.Edit
        ) {
            router.actions.push(urls.sqlEditor(undefined, undefined, insightId))
        }
    }, [insightId, insight?.query?.kind, insightMode, featureFlags])

    if (
        featureFlags[FEATURE_FLAGS.SCENE_TABS] &&
        insightId &&
        insight?.query?.kind === NodeKind.DataVisualizationNode &&
        insightMode === ItemMode.Edit
    ) {
        return <EditorScene tabId={tabId} />
    }

    if (
        insightId === 'new' ||
        insightId?.startsWith('new-') ||
        (insightId &&
            insight?.id &&
            insight?.short_id &&
            (insight?.query?.kind !== NodeKind.DataVisualizationNode || insightMode !== ItemMode.Edit))
    ) {
        return <InsightAsScene insightId={insightId} tabId={tabId} attachTo={insightSceneLogic({ tabId })} />
    }

    if (insightLogicRef?.logic?.values?.insightLoading) {
        return <InsightSkeleton />
    }

    return <NotFound object="insight" />
}

export const scene: SceneExport = {
    component: InsightScene,
    logic: insightSceneLogic,
    settingSectionId: 'environment-product-analytics',
}

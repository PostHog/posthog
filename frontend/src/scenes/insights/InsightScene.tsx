import { SceneExport } from 'scenes/sceneTypes'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'
import { useValues } from 'kea'
import { Insight } from 'scenes/insights/Insight'
import { InsightSkeleton } from 'scenes/insights/InsightSkeleton'
import { NotFound } from 'lib/components/NotFound'
import { Query } from '~/queries/Query/Query'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { NodeKind } from '~/queries/schema'
import { nodeKindToDefaultQuery } from '~/queries/nodes/InsightQuery/defaults'

function InsightSceneDataExploration(): JSX.Element {
    const { insightId, insight, insightCache } = useValues(insightSceneLogic)
    //     const { query } = useValues(insightDataLogic(insightProps))
    // const { setQuery } = useActions(insightDataLogic(insightProps))
    // insightQueryLogic

    return (
        <Query
            query={{
                kind: NodeKind.InsightVizNode,
                insightId,
                // insightId: 'new' | InsightShortId | null,
                // showFilters: edit
                source: nodeKindToDefaultQuery[NodeKind.TrendsQuery],
                // full: true,
                // showEventFilter: false,
                // showPropertyFilter: false,
            }}
        />
    )
}

export function InsightScene(): JSX.Element {
    const { insightId, insight, insightCache } = useValues(insightSceneLogic)

    if (insightId === 'new' || (insightId && insight?.id && insight?.short_id)) {
        return <Insight insightId={insightId} />
    }

    if (insightCache?.logic?.values?.insightLoading) {
        return <InsightSkeleton />
    }

    return <NotFound object={'insight'} />
}

function FeatureFlaggedInsightScene(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    return featureFlags[FEATURE_FLAGS.DATA_EXPLORATION_INSIGHTS] ? <InsightSceneDataExploration /> : <InsightScene />
}

export const scene: SceneExport = {
    component: FeatureFlaggedInsightScene,
    logic: insightSceneLogic,
}

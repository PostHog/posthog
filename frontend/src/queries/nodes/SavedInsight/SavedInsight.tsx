import { useValues } from 'kea'

import { insightLogic } from 'scenes/insights/insightLogic'
import { Query } from '~/queries/Query/Query'
import { SavedInsightNode, NodeKind, QueryContext } from '~/queries/schema'
import { InsightLogicProps, InsightModel } from '~/types'
import { Animation } from 'lib/components/Animation/Animation'
import { AnimationType } from 'lib/animations/animations'
import { filtersToQueryNode } from '../InsightQuery/utils/filtersToQueryNode'

interface InsightProps {
    query: SavedInsightNode
    cachedResults?: Partial<InsightModel> | null
    context?: QueryContext
}

export function SavedInsight({ query, context, cachedResults }: InsightProps): JSX.Element {
    const insightProps: InsightLogicProps = { dashboardItemId: query.shortId, cachedInsight: cachedResults }
    const { insight, insightLoading } = useValues(insightLogic(insightProps))

    if (insightLoading) {
        return (
            <div className="text-center">
                <Animation type={AnimationType.LaptopHog} />
            </div>
        )
    }

    if (!insight.filters) {
        throw new Error('InsightNode expects an insight with filters')
    }

    return (
        <Query
            query={{ ...query, kind: NodeKind.InsightVizNode, source: filtersToQueryNode(insight.filters) }}
            context={{ ...context, insightProps }}
        />
    )
}

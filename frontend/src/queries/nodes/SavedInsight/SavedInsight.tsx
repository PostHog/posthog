import { useValues } from 'kea'

import { insightLogic } from 'scenes/insights/insightLogic'
import { Query } from '~/queries/Query/Query'
import { SavedInsightNode, QueryContext } from '~/queries/schema'
import { InsightLogicProps, InsightModel } from '~/types'
import { Animation } from 'lib/components/Animation/Animation'
import { AnimationType } from 'lib/animations/animations'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'

interface InsightProps {
    query: SavedInsightNode
    cachedResults?: Partial<InsightModel> | null
    context?: QueryContext
}

export function SavedInsight({ query: propsQuery, context, cachedResults }: InsightProps): JSX.Element {
    const insightProps: InsightLogicProps = { dashboardItemId: propsQuery.shortId, cachedInsight: cachedResults }
    const { insight, insightLoading } = useValues(insightLogic(insightProps))
    const { query: dataQuery } = useValues(insightDataLogic(insightProps))

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

    const query = { ...propsQuery, ...dataQuery, full: propsQuery.full }

    return <Query query={query} context={{ ...context, insightProps }} />
}

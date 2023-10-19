import { useValues } from 'kea'

import { insightLogic } from 'scenes/insights/insightLogic'
import { Query } from '~/queries/Query/Query'
import { SavedInsightNode } from '~/queries/schema'
import { QueryContext } from '~/queries/types'

import { InsightLogicProps } from '~/types'
import { Animation } from 'lib/components/Animation/Animation'
import { AnimationType } from 'lib/animations/animations'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'

interface InsightProps {
    query: SavedInsightNode
    context?: QueryContext
}

export function SavedInsight({ query: propsQuery, context }: InsightProps): JSX.Element {
    const insightProps: InsightLogicProps = { dashboardItemId: propsQuery.shortId }
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

    return <Query query={query} cachedResults={insight.result} context={{ ...context, insightProps }} />
}

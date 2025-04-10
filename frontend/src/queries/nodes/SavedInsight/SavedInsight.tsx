import { useValues } from 'kea'
import { LoadingBar } from 'lib/lemon-ui/LoadingBar'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'

import { Query } from '~/queries/Query/Query'
import { SavedInsightNode } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'
import { InsightLogicProps } from '~/types'

interface InsightProps {
    query: SavedInsightNode
    context?: QueryContext
    embedded?: boolean
    readOnly?: boolean
}

export function SavedInsight({ query: propsQuery, context, embedded, readOnly }: InsightProps): JSX.Element {
    const insightProps: InsightLogicProps = { dashboardItemId: propsQuery.shortId }
    const { insight, insightLoading } = useValues(insightLogic(insightProps))
    const { query: dataQuery } = useValues(insightDataLogic(insightProps))

    if (insightLoading) {
        return (
            <div className="text-center">
                <LoadingBar />
            </div>
        )
    }

    const query = { ...propsQuery, ...dataQuery, full: propsQuery.full }

    return (
        <Query
            query={query}
            cachedResults={insight}
            context={{ ...context, insightProps }}
            embedded={embedded}
            readOnly={readOnly}
        />
    )
}

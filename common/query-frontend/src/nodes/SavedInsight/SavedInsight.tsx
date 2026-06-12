import { BuiltLogic, LogicWrapper, useValues } from 'kea'

import { insightDataLogic } from '@posthog/query-frontend/nodes/InsightViz/insightDataLogic'
import { Query } from '@posthog/query-frontend/Query/Query'
import { SavedInsightNode } from '@posthog/query-frontend/schema/schema-general'
import { QueryContext } from '@posthog/query-frontend/types'

import { LoadingBar } from 'lib/lemon-ui/LoadingBar'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { insightLogic } from 'scenes/insights/insightLogic'

import { InsightLogicProps } from '~/types'

interface InsightProps {
    query: SavedInsightNode
    context?: QueryContext
    embedded?: boolean
    readOnly?: boolean
    /** Attach ourselves to another logic, such as the scene logic */
    attachTo?: BuiltLogic | LogicWrapper
    editMode?: boolean
}

export function SavedInsight({
    query: propsQuery,
    context,
    embedded,
    readOnly,
    attachTo,
    editMode,
}: InsightProps): JSX.Element {
    const insightProps: InsightLogicProps = { dashboardItemId: propsQuery.shortId }
    const { insight, insightLoading } = useValues(insightLogic(insightProps))
    const { query: dataQuery } = useValues(insightDataLogic(insightProps))

    useAttachedLogic(insightLogic(insightProps), attachTo)
    useAttachedLogic(insightDataLogic(insightProps), attachTo)

    if (insightLoading) {
        return (
            <div className="flex flex-col flex-1 justify-center items-center w-full h-full">
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
            editMode={editMode}
        />
    )
}

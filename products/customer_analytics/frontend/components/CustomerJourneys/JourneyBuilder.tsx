import { useActions, useValues } from 'kea'

import { InsightViz } from '@posthog/query-frontend/nodes/InsightViz/InsightViz'
import { FunnelsQuery, InsightVizNode } from '@posthog/query-frontend/schema/schema-general'
import { QueryContext } from '@posthog/query-frontend/types'

import { InsightLogicProps } from '~/types'

import { JOURNEY_BUILDER_INSIGHT_PROPS, journeyBuilderLogic } from './journeyBuilderLogic'

const JOURNEY_BUILDER_CONTEXT: QueryContext<InsightVizNode> = {
    insightProps: JOURNEY_BUILDER_INSIGHT_PROPS as InsightLogicProps<InsightVizNode>,
}

export function JourneyBuilder(): JSX.Element {
    const { query } = useValues(journeyBuilderLogic)
    const { setQueryFromViz } = useActions(journeyBuilderLogic)

    return (
        <InsightViz
            query={query}
            setQuery={(node) => setQueryFromViz(node as InsightVizNode<FunnelsQuery>)}
            editMode={true}
            uniqueKey="journey-builder"
            context={JOURNEY_BUILDER_CONTEXT}
        />
    )
}

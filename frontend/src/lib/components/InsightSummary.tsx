import { InsightModel } from '~/types'
import { groupsModel } from '~/models/groupsModel'
import { cohortsModel } from '~/models/cohortsModel'
import { mathsLogic } from 'scenes/trends/mathsLogic'
import { summarizeInsightFilters, summarizeInsightQuery } from 'scenes/insights/utils'
import { isInsightVizNode } from '~/queries/utils'
import { InsightVizNode, Node } from '~/queries/schema'
import { useValues } from 'kea'

type InsightSummaryProps = { insight: Partial<InsightModel>; isUsingDataExploration: boolean; inflightQuery?: Node }

export function insightSummaryString(props: InsightSummaryProps): string {
    const { aggregationLabel } = useValues(groupsModel)
    const { cohortsById } = useValues(cohortsModel)
    const { mathDefinitions } = useValues(mathsLogic)

    const { insight } = props
    const { filters } = insight

    const query = props.inflightQuery || insight.query

    console.log('insightSummaryString', props, query, filters)

    return !!props.insight.name
        ? props.insight.name
        : props.isUsingDataExploration && isInsightVizNode(query)
        ? summarizeInsightQuery((query as InsightVizNode).source, aggregationLabel, cohortsById, mathDefinitions)
        : !!query
        ? 'query: ' + query.kind
        : !!filters && !!Object.keys(filters).length
        ? summarizeInsightFilters(filters, aggregationLabel, cohortsById, mathDefinitions)
        : 'unknown insight type'
}

export function InsightSummary(props: InsightSummaryProps): JSX.Element {
    return <>{props.insight.name || <i>{insightSummaryString(props)}</i>}</>
}

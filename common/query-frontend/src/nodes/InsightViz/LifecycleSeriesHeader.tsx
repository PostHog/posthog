import { useValues } from 'kea'

import { AggregationSelect } from '@posthog/query-frontend/nodes/InsightViz/filters/AggregationSelect'
import { getAggregationTargetPronoun } from '@posthog/query-frontend/nodes/InsightViz/filters/aggregationTargetUtils'
import { insightVizDataLogic } from '@posthog/query-frontend/nodes/InsightViz/insightVizDataLogic'
import { LifecycleQuery } from '@posthog/query-frontend/schema/schema-general'

import { insightLogic } from 'scenes/insights/insightLogic'

import { groupsModel } from '~/models/groupsModel'

export function LifecycleSeriesHeader(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { aggregationGroupTypeIndex, querySource, hasDataWarehouseSeries } = useValues(
        insightVizDataLogic(insightProps)
    )
    const { showGroupsOptions } = useValues(groupsModel)
    const showAggregationSelect = showGroupsOptions || hasDataWarehouseSeries
    const customAggregationTarget = (querySource as LifecycleQuery | null)?.customAggregationTarget === true

    return (
        <div className="leading-6">
            <div className="flex items-center">
                Showing
                {showAggregationSelect ? (
                    <AggregationSelect className="mx-2" insightProps={insightProps} hogqlAvailable={false} />
                ) : (
                    <b> Unique users </b>
                )}
                {getAggregationTargetPronoun(aggregationGroupTypeIndex, customAggregationTarget)} did
            </div>
        </div>
    )
}

import { useValues } from 'kea'

import { groupsModel } from '~/models/groupsModel'

import { AggregationSelect } from 'scenes/insights/filters/AggregationSelect'
import { getAggregationTargetPronoun } from 'scenes/insights/filters/aggregationTargetUtils'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

export function LifecycleSeriesHeader(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { aggregationGroupTypeIndex } = useValues(insightVizDataLogic(insightProps))
    const { showGroupsOptions } = useValues(groupsModel)

    return (
        <div className="leading-6">
            <div className="flex items-center">
                Showing
                {showGroupsOptions ? (
                    <AggregationSelect className="mx-2" insightProps={insightProps} hogqlAvailable={false} />
                ) : (
                    <b> Unique users </b>
                )}
                {getAggregationTargetPronoun(aggregationGroupTypeIndex)} did
            </div>
        </div>
    )
}

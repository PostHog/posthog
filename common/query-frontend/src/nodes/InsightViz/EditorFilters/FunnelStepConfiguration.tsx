import { useValues } from 'kea'

import { FunnelConversionWindowFilter } from '@posthog/query-frontend/nodes/FunnelsQuery/views/FunnelConversionWindowFilter'

import { groupsModel } from '~/models/groupsModel'
import { EditorFilterProps } from '~/types'

import { AggregationSelect } from '../filters/AggregationSelect'

export function FunnelStepConfiguration({ insightProps }: EditorFilterProps): JSX.Element {
    const { showGroupsOptions } = useValues(groupsModel)

    return (
        <div className="flex flex-col gap-4">
            {showGroupsOptions && (
                <div className="flex items-center w-full gap-2" data-attr="funnel-aggregation-filter">
                    <span>Aggregating by</span>
                    <AggregationSelect insightProps={insightProps} hogqlAvailable />
                </div>
            )}
            <FunnelConversionWindowFilter insightProps={insightProps} />
        </div>
    )
}

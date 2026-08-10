import { useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { groupsModel } from '~/models/groupsModel'
import { isFunnelsQuery } from '~/queries/utils'
import { EditorFilterProps } from '~/types'

import { AggregationSelect, isCustomHogQLAggregation } from '../filters/AggregationSelect'
import { FunnelConversionWindowFilter } from '../views/Funnels/FunnelConversionWindowFilter'

export function FunnelStepConfiguration({ insightProps }: EditorFilterProps): JSX.Element {
    const { showGroupsOptions } = useValues(groupsModel)
    const { querySource } = useValues(insightVizDataLogic(insightProps))

    const aggregatesByExpression =
        isFunnelsQuery(querySource) && isCustomHogQLAggregation(querySource.funnelsFilter?.funnelAggregateByHogQL)

    return (
        <div className="flex flex-col gap-4">
            {showGroupsOptions && (
                <div className="flex items-center w-full gap-2" data-attr="funnel-aggregation-filter">
                    <span>Aggregating by</span>
                    <AggregationSelect insightProps={insightProps} hogqlAvailable />
                </div>
            )}
            {aggregatesByExpression && (
                <LemonBanner type="warning">
                    This funnel aggregates by a custom SQL expression. PostHog drops any event that does not have this
                    value. A step whose events lack it then converts at 0%. Make sure every step's events carry this
                    value, or aggregate by unique users instead.
                </LemonBanner>
            )}
            <FunnelConversionWindowFilter insightProps={insightProps} />
        </div>
    )
}

import { useActions, useValues } from 'kea'

import { CompareFilter } from 'lib/components/CompareFilter/CompareFilter'
import { IntervalFilter } from 'lib/components/IntervalFilter/IntervalFilter'
import { InsightDateFilter } from 'scenes/insights/filters/InsightDateFilter/InsightDateFilter'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { EditorFilterProps } from '~/types'

export function DateRangeFilter({ insightProps }: EditorFilterProps): JSX.Element {
    const {
        isTrends,
        isFunnels,
        isStickiness,
        isRetention,
        isLifecycle,
        isTrendsFunnel,
        compareFilter,
        supportsCompare,
    } = useValues(insightVizDataLogic(insightProps))
    const { updateCompareFilter } = useActions(insightVizDataLogic(insightProps))
    const { canEditInsight } = useValues(insightLogic(insightProps))

    const showInterval = isTrendsFunnel || isLifecycle || isTrends || isStickiness
    const showCompare = (isTrends || isStickiness) && supportsCompare

    return (
        <div className="flex flex-col gap-3">
            {!isRetention && <InsightDateFilter disabled={isFunnels} />}
            {showInterval && (
                <div className="flex items-center gap-2">
                    <span className="text-xs text-secondary whitespace-nowrap">Interval</span>
                    <IntervalFilter />
                </div>
            )}
            {showCompare && (
                <CompareFilter
                    compareFilter={compareFilter}
                    updateCompareFilter={updateCompareFilter}
                    disabled={!canEditInsight}
                />
            )}
        </div>
    )
}

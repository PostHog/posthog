import { LemonCheckbox } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { RollingDateRangeFilter } from 'lib/components/DateFilter/RollingDateRangeFilter'
import { useState } from 'react'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { getDefaultComparisonPeriodRelativeStartDate } from './compareFilterLogic'

export function CompareFilter(): JSX.Element | null {
    const { insightProps, canEditInsight } = useValues(insightLogic)

    const { compare, comparison, supportsCompare, dateRange, interval } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    const disabled: boolean = !canEditInsight || !supportsCompare
    const defaultRelativePeriod = getDefaultComparisonPeriodRelativeStartDate(dateRange, interval)
    const [relativePeriodStart, setRelativePeriodStart] = useState(defaultRelativePeriod)

    // Hide compare filter control when disabled to avoid states where control is "disabled but checked"
    if (disabled) {
        return null
    }

    return (
        <>
            <LemonCheckbox
                onChange={(compare: boolean) => {
                    if (!compare) {
                        updateInsightFilter({ compare: undefined, comparison: undefined })
                    } else {
                        updateInsightFilter({
                            compare,
                            comparison: {
                                relative_period_start: relativePeriodStart,
                            },
                        })
                    }
                }}
                checked={!!compare}
                label={<span className="font-normal">Compare to the period starting</span>}
                size="small"
                className="ml-4"
            />
            <RollingDateRangeFilter
                dateFrom={relativePeriodStart}
                dateRangeFilterLabel=""
                selected={true}
                onChange={(period) => {
                    setRelativePeriodStart(period)
                    if (comparison) {
                        updateInsightFilter({
                            comparison: {
                                relative_period_start: period,
                            },
                        })
                    }
                }}
                allowedDateOptions={['hours', 'days', 'weeks', 'months', 'years']}
            />
            <span className="font-normal">ago</span>
        </>
    )
}

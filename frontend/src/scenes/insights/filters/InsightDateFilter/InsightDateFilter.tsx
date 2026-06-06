import { useActions, useValues } from 'kea'

import { IconCalendar } from '@posthog/icons'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { dateMapping } from 'lib/utils'
import { alignResolvedDateRangeToInterval } from 'lib/utils/dateTimeUtils'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

type InsightDateFilterProps = {
    disabled: boolean
}

export function InsightDateFilter({ disabled }: InsightDateFilterProps): JSX.Element {
    const { insightProps, editingDisabledReason } = useValues(insightLogic)
    const { dateRange, interval } = useValues(insightVizDataLogic(insightProps))
    const { updateDateRange } = useActions(insightVizDataLogic(insightProps))
    const { insightData } = useValues(insightVizDataLogic(insightProps))

    return (
        <DateFilter
            showExplicitDateToggle
            dateTo={dateRange?.date_to ?? undefined}
            dateFrom={dateRange?.date_from ?? '-7d'}
            explicitDate={dateRange?.explicitDate ?? false}
            allowTimePrecision
            allowFixedRangeWithTime
            disabled={disabled}
            disabledReason={editingDisabledReason}
            onChange={(date_from, date_to, explicit_date) => {
                // Prevent debouncing when toggling the exact time range toggle as it glitches the animation
                const ignoreDebounce = dateRange?.explicitDate !== explicit_date
                updateDateRange({ date_from, date_to, explicitDate: explicit_date }, ignoreDebounce)
            }}
            dateOptions={dateMapping}
            allowedRollingDateOptions={['hours', 'days', 'weeks', 'months', 'years']}
            resolvedDateRange={alignResolvedDateRangeToInterval(insightData?.resolved_date_range, interval)}
            makeLabel={(key) => (
                <>
                    <IconCalendar /> {key}
                </>
            )}
        />
    )
}

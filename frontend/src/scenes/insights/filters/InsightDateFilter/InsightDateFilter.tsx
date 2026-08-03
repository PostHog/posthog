import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { IconCalendar } from '@posthog/icons'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { type DateFilterExclusions } from 'lib/components/DateFilter/DateFilterExclusionsControl'
import { dateMapping } from 'lib/utils/dateFilters'
import { alignResolvedDateRangeToInterval } from 'lib/utils/datetime'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import {
    computeDaysOfWeekUpdate,
    daysOfWeekSetsEqual,
    getExcludedDaysOfWeek,
    parseIsoDaysOfWeek,
    querySupportsDaysOfWeek,
} from './daysOfWeekFilterUtils'

type InsightDateFilterProps = {
    disabled: boolean
}

export function InsightDateFilter({ disabled }: InsightDateFilterProps): JSX.Element {
    const { insightProps, editingDisabledReason } = useValues(insightLogic)
    const { dateRange, interval, querySource, trendsFilter, isTrends } = useValues(insightVizDataLogic(insightProps))
    const { updateDateRange, updateQuerySource } = useActions(insightVizDataLogic(insightProps))
    const { insightData } = useValues(insightVizDataLogic(insightProps))
    const { reportInsightDatePickerOpened } = useActions(eventUsageLogic)

    // The picker speaks excluded days; the query schema stores included days
    const excludedDaysOfWeek = getExcludedDaysOfWeek(dateRange)
    const supportsDaysOfWeek = querySupportsDaysOfWeek(querySource)
    // The backend rejects daysOfWeek together with smoothing, so don't offer it
    const smoothingActive = isTrends && (trendsFilter?.smoothingIntervals ?? 1) > 1
    const showDaysOfWeekExclusions = supportsDaysOfWeek && !smoothingActive

    // Enabling smoothing hides the control, so clear daysOfWeek on that transition (never on
    // mount): the backend rejects the combination and there'd be no UI left to remove it
    const prevShowDaysOfWeekExclusions = useRef(showDaysOfWeekExclusions)
    useEffect(() => {
        const wasShown = prevShowDaysOfWeekExclusions.current
        prevShowDaysOfWeekExclusions.current = showDaysOfWeekExclusions
        if (wasShown && !showDaysOfWeekExclusions && smoothingActive && dateRange?.daysOfWeek?.length) {
            updateQuerySource(computeDaysOfWeekUpdate([], dateRange))
        }
    }, [showDaysOfWeekExclusions, smoothingActive, dateRange, updateQuerySource])

    const exclusions: DateFilterExclusions = {
        days: showDaysOfWeekExclusions ? excludedDaysOfWeek.map(String) : [],
        incomplete: !!dateRange?.excludeIncompletePeriods,
    }
    const handleExclusionsChange = (next: DateFilterExclusions): void => {
        const nextExcludedDaysOfWeek = parseIsoDaysOfWeek(next.days)
        if (showDaysOfWeekExclusions && !daysOfWeekSetsEqual(nextExcludedDaysOfWeek, excludedDaysOfWeek)) {
            updateQuerySource(computeDaysOfWeekUpdate(nextExcludedDaysOfWeek, dateRange))
        }
        if (next.incomplete !== exclusions.incomplete) {
            updateDateRange({ excludeIncompletePeriods: next.incomplete ? true : null }, true)
        }
    }

    return (
        <DateFilter
            showExplicitDateToggle
            dateTo={dateRange?.date_to ?? undefined}
            dateFrom={dateRange?.date_from ?? '-7d'}
            explicitDate={dateRange?.explicitDate ?? false}
            exclusions={exclusions}
            onExclusionsChange={handleExclusionsChange}
            showIncompletePeriodExclusion
            showDaysOfWeekExclusions={showDaysOfWeekExclusions}
            optionsSize="small"
            allowTimePrecision
            allowFixedRangeWithTime
            disabled={disabled}
            disabledReason={editingDisabledReason}
            onOpenChange={(open) => {
                if (open) {
                    reportInsightDatePickerOpened(querySource?.kind)
                }
            }}
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

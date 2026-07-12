import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { IconCalendar } from '@posthog/icons'
import { Button, CUSTOM_RANGE, Day } from '@posthog/quill'

import { DateExclusionsControl } from 'lib/components/DateRangeFilter/DateExclusionsControl'
import { DateRangeFilter, type DateRangePreset } from 'lib/components/DateRangeFilter/DateRangeFilter'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { teamLogic } from 'scenes/teamLogic'

import {
    ALL_DAY_NUMBERS,
    computeDaysOfWeekUpdate,
    daysOfWeekLabel,
    getEffectiveDaysOfWeek,
    type IsoDayOfWeek,
} from './daysOfWeekFilterUtils'
import {
    ALL_TIME_PRESET,
    DEFAULT_DATE_FROM,
    INSIGHT_DATE_PRESETS,
    type InsightDatePreset,
    dateRangeUpdateForPickerValue,
    insightDateLabel,
    insightDateRanges,
    pickerValueForDateRange,
    presetForDateStrings,
    retentionDatePresets,
} from './insightDateFilterNextUtils'

const ROLLING_DATE_FROM = /^-(\d+)([hdwmy])$/

type InsightDateFilterNextProps = {
    disabled: boolean
}

export function InsightDateFilterNext({ disabled }: InsightDateFilterNextProps): JSX.Element {
    const { insightProps, editingDisabledReason } = useValues(insightLogic)
    const { querySource, dateRange, trendsFilter, retentionFilter, isTrends, isRetention } = useValues(
        insightVizDataLogic(insightProps)
    )
    const { updateDateRange, updateQuerySource } = useActions(insightVizDataLogic(insightProps))
    const { weekStartDay } = useValues(teamLogic)

    // Retention's range selects cohort-start buckets, so its presets scale with the period.
    const retentionPeriod = isRetention ? (retentionFilter?.period ?? 'Day') : null
    const presets = useMemo(
        () => [...(retentionPeriod ? retentionDatePresets(retentionPeriod) : INSIGHT_DATE_PRESETS), ALL_TIME_PRESET],
        [retentionPeriod]
    )

    const ranges = useMemo(() => insightDateRanges(weekStartDay, presets), [weekStartDay, presets])
    const pickerValue = useMemo(
        () => pickerValueForDateRange(dateRange?.date_from, dateRange?.date_to, ranges, undefined, presets),
        [dateRange?.date_from, dateRange?.date_to, ranges, presets]
    )

    // The filter couriers each preset back verbatim; PostHog's relative date strings ride in `value`.
    const filterPresets = useMemo(
        (): DateRangePreset<InsightDatePreset>[] =>
            presets.map((preset) => ({
                id: preset.dateFrom,
                label: preset.name,
                value: preset,
                previewStart: (now: Date) => preset.rangeSetter(now, weekStartDay),
                previewEnd: preset.endSetter ? (now: Date) => preset.endSetter!(now, weekStartDay) : undefined,
            })),
        [presets, weekStartDay]
    )

    const activePreset = presetForDateStrings(dateRange?.date_from ?? DEFAULT_DATE_FROM, dateRange?.date_to, presets)
    const isRolling = ROLLING_DATE_FROM.test(dateRange?.date_from ?? '')
    const isCustom = pickerValue.range.id === CUSTOM_RANGE.id && !isRolling && !!dateRange?.date_from

    // The exclusions control speaks excluded days; the query schema stores included days.
    const includedDays = getEffectiveDaysOfWeek(dateRange, trendsFilter)
    const excludedDays = includedDays.length === 0 ? [] : ALL_DAY_NUMBERS.filter((day) => !includedDays.includes(day))
    const setExcludedDays = (excluded: number[]): void => {
        const included = excluded.length === 0 ? [] : ALL_DAY_NUMBERS.filter((day) => !excluded.includes(day))
        updateQuerySource(computeDaysOfWeekUpdate(included as IsoDayOfWeek[], querySource, dateRange))
    }

    const labelParts = [insightDateLabel(dateRange?.date_from, dateRange?.date_to, presets)]
    if (isTrends && includedDays.length > 0) {
        labelParts.push(daysOfWeekLabel(includedDays))
    }
    if (dateRange?.excludeIncompletePeriods) {
        labelParts.push('Excl. incomplete')
    }

    const showExclusions = isTrends || !isRetention
    const footerExtra = showExclusions ? (
        <DateExclusionsControl
            excludedDays={isTrends ? excludedDays : undefined}
            onExcludedDaysChange={isTrends ? setExcludedDays : undefined}
            excludeIncomplete={!isRetention ? !!dateRange?.excludeIncompletePeriods : undefined}
            onExcludeIncompleteChange={
                !isRetention
                    ? (checked) => updateDateRange({ excludeIncompletePeriods: checked ? true : null }, true)
                    : undefined
            }
        />
    ) : undefined

    // data-lemon-skin opts these surfaces into the quill-as-lemon skin (lemon-skin.scss) so the
    // filter sits next to Lemon chrome without a visual jump. The trigger carries it directly;
    // the popover surface portals to <body>, so it rides in via contentProps.
    return (
        <DateRangeFilter
            presets={filterPresets}
            selectedPresetId={activePreset?.dateFrom ?? null}
            onPresetSelect={(preset) =>
                updateDateRange({ date_from: preset.value!.dateFrom, date_to: preset.value!.dateTo }, true)
            }
            onCustomApply={(start, end) =>
                updateDateRange(dateRangeUpdateForPickerValue({ start, end, range: CUSTOM_RANGE }, presets), true)
            }
            customActive={isCustom}
            customStart={isCustom ? pickerValue.start : undefined}
            customEnd={isCustom ? pickerValue.end : undefined}
            weekStartsOn={weekStartDay === 1 ? Day.MONDAY : Day.SUNDAY}
            footerExtra={footerExtra}
            contentProps={
                { 'data-lemon-skin': 'true' } as unknown as React.ComponentProps<typeof DateRangeFilter>['contentProps']
            }
            trigger={
                <Button
                    variant="outline"
                    size="default"
                    data-attr="insight-date-filter-next"
                    data-quill
                    data-lemon-skin
                    disabled={disabled || !!editingDisabledReason}
                    title={editingDisabledReason ?? undefined}
                >
                    <IconCalendar />
                    {labelParts.join(' · ')}
                </Button>
            }
        />
    )
}

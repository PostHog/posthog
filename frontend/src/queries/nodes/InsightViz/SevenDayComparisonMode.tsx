import { useActions, useValues } from 'kea'

import { LemonSegmentedButton } from '@posthog/lemon-ui'

import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

const LEGACY_DATE_FROM = '-7d'
const SEVEN_CALENDAR_DAYS_DATE_FROM = '-6d'

export function SevenDayComparisonMode(): JSX.Element | null {
    const { insightProps, canEditInsight, editingDisabledReason } = useValues(insightLogic)
    const { isTrends, compareFilter, dateRange, interval } = useValues(insightVizDataLogic(insightProps))
    const { updateDateRange } = useActions(insightVizDataLogic(insightProps))

    const isSupportedDateRange =
        !dateRange?.date_to &&
        (dateRange?.date_from === LEGACY_DATE_FROM || dateRange?.date_from === SEVEN_CALENDAR_DAYS_DATE_FROM)

    if (!isTrends || !compareFilter?.compare || interval !== 'day' || !isSupportedDateRange) {
        return null
    }

    return (
        <LemonSegmentedButton
            value={dateRange?.date_from ?? undefined}
            onChange={(dateFrom: string) => updateDateRange({ date_from: dateFrom }, true)}
            options={[
                {
                    value: LEGACY_DATE_FROM,
                    label: 'Legacy',
                    tooltip:
                        'Seven days ago through today, resulting in eight calendar days and an overlapping comparison day',
                    'data-attr': 'seven-day-comparison-mode-legacy',
                },
                {
                    value: SEVEN_CALENDAR_DAYS_DATE_FROM,
                    label: 'Seven calendar days',
                    tooltip: 'Today and the six preceding days, compared with the previous seven non-overlapping days',
                    'data-attr': 'seven-day-comparison-mode-calendar',
                },
            ]}
            disabledReason={
                canEditInsight ? undefined : (editingDisabledReason ?? "You don't have permission to edit this insight")
            }
            size="small"
        />
    )
}

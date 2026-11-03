import { useActions, useValues } from 'kea'

import { IconRewind } from '@posthog/icons'

import { COMPARE_ALL_TIME_DISABLED_REASON } from 'lib/components/CompareFilter/CompareFilter'
import { FilterBarOption, FilterBarOptionControl } from 'lib/components/FilterBar/FilterBarOptionControl'
import { dateFromToText } from 'lib/utils/dateFilters'
import { DashboardEventSource } from 'lib/utils/eventUsageLogic'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'

import { CompareFilter } from '~/queries/schema/schema-general'

const COMPARE_TO_PERIODS = ['-1d', '-1w', '-1m', '-1y']

function optionForCompareFilter(compareFilter: CompareFilter | null | undefined): string | null {
    if (compareFilter == null) {
        return null
    }
    if (!compareFilter.compare) {
        return 'none'
    }
    return compareFilter.compare_to || 'previous'
}

function compareFilterForOption(option: string): CompareFilter {
    if (option === 'none') {
        return { compare: false }
    }
    if (option === 'previous') {
        return { compare: true }
    }
    return { compare: true, compare_to: option }
}

export function DashboardComparisonControl(): JSX.Element | null {
    const { dashboardEditing, effectiveEditBarFilters } = useValues(dashboardLogic)
    const { setCompareFilter, setDashboardEditing } = useActions(dashboardLogic)
    const value = optionForCompareFilter(effectiveEditBarFilters.compareFilter)
    // All time has no earlier period, so only "No comparison" stays pickable.
    const disabledReason = effectiveEditBarFilters.date_from === 'all' ? COMPARE_ALL_TIME_DISABLED_REASON : undefined
    // A period saved from elsewhere, such as "-3m", stays offered so the chip can name it.
    const periods =
        value && !['none', 'previous', ...COMPARE_TO_PERIODS].includes(value)
            ? [...COMPARE_TO_PERIODS, value]
            : COMPARE_TO_PERIODS

    const options: FilterBarOption[] = [
        { value: 'none', label: 'No comparison' },
        { value: 'previous', label: 'Previous period', disabledReason },
        ...periods.map((period) => ({
            value: period,
            label: `${dateFromToText(period) ?? period} earlier`,
            disabledReason,
        })),
    ]

    return (
        <FilterBarOptionControl
            id="comparison"
            label="Compared to"
            icon={IconRewind}
            value={value}
            options={options}
            onChange={(next) => {
                if (!dashboardEditing?.filters) {
                    setDashboardEditing({ filters: true, layout: false }, DashboardEventSource.DashboardFilters)
                }
                setCompareFilter(next === null ? null : compareFilterForOption(next))
            }}
            data-attr="dashboard-compare-filter"
        />
    )
}

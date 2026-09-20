import { useActions, useValues } from 'kea'

import { COMPARE_ALL_TIME_DISABLED_REASON, CompareFilter } from 'lib/components/CompareFilter/CompareFilter'
import { DashboardEventSource } from 'lib/utils/eventUsageLogic'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'

import { CompareFilter as CompareFilterType } from '~/queries/schema/schema-general'

export function DashboardCompareFilter(): JSX.Element {
    const { dashboardEditing, effectiveEditBarFilters } = useValues(dashboardLogic)
    const { setCompareFilter, setDashboardEditing } = useActions(dashboardLogic)

    const isAllTime = effectiveEditBarFilters.date_from === 'all'

    const updateCompareFilter = (compareFilter: CompareFilterType | null): void => {
        if (!dashboardEditing?.filters) {
            setDashboardEditing({ filters: true, layout: false }, DashboardEventSource.DashboardFilters)
        }
        setCompareFilter(compareFilter)
    }

    return (
        <CompareFilter
            compareFilter={effectiveEditBarFilters.compareFilter}
            inheritLabel="each insight's comparison"
            onInherit={() => updateCompareFilter(null)}
            updateCompareFilter={updateCompareFilter}
            disabled={isAllTime}
            disableReason={isAllTime ? COMPARE_ALL_TIME_DISABLED_REASON : null}
        />
    )
}

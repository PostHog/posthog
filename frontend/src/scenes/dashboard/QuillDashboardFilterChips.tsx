import { useActions, useValues } from 'kea'

import { Chip, ChipClose } from '@posthog/quill'

import { formatPropertyLabel, propertyFilterTypeToPropertyDefinitionType } from 'lib/components/PropertyFilters/utils'
import { DashboardEventSource } from 'lib/utils/eventUsageLogic'
import {
    DashboardActiveFilter,
    breakdownFilterLabel,
    compareFilterLabel,
    getDashboardActiveFilters,
    intervalFilterLabel,
    testAccountsFilterLabel,
} from 'scenes/dashboard/dashboardActiveFilters'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'

import { cohortsModel } from '~/models/cohortsModel'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { GroupPropertyFilter, GroupTypeIndex } from '~/types'

/** The dashboard overrides in force, each as a chip that removes it. Nothing renders when no override is set. */
export function QuillDashboardFilterChips(): JSX.Element | null {
    const { dashboardEditing, effectiveEditBarFilters } = useValues(dashboardLogic)
    const {
        setProperties,
        setBreakdownFilter,
        setInterval,
        setFilterTestAccounts,
        setCompareFilter,
        setDashboardEditing,
    } = useActions(dashboardLogic)
    const { cohortsById } = useValues(cohortsModel)
    const { formatPropertyValueForDisplay } = useValues(propertyDefinitionsModel)

    const activeFilters = getDashboardActiveFilters(effectiveEditBarFilters)
    if (activeFilters.length === 0) {
        return null
    }

    const label = (active: DashboardActiveFilter): string => {
        switch (active.kind) {
            case 'property': {
                const { filter } = active
                return formatPropertyLabel(filter, cohortsById, (value) =>
                    String(
                        formatPropertyValueForDisplay(
                            filter.key,
                            value,
                            propertyFilterTypeToPropertyDefinitionType(filter.type),
                            (filter as GroupPropertyFilter).group_type_index as GroupTypeIndex | undefined
                        ) ?? value
                    )
                )
            }
            case 'breakdown':
                return breakdownFilterLabel(active.breakdownFilter)
            case 'interval':
                return intervalFilterLabel(active.interval)
            case 'testAccounts':
                return testAccountsFilterLabel(active.filterTestAccounts)
            case 'compare':
                return compareFilterLabel(active.compareFilter)
        }
    }

    const remove = (active: DashboardActiveFilter): void => {
        if (!dashboardEditing?.filters) {
            setDashboardEditing({ filters: true, layout: false }, DashboardEventSource.DashboardFilters)
        }
        switch (active.kind) {
            case 'property': {
                const remaining = (effectiveEditBarFilters.properties ?? []).filter((_, i) => i !== active.index)
                setProperties(remaining.length ? remaining : null)
                return
            }
            case 'breakdown':
                setBreakdownFilter(null)
                return
            case 'interval':
                setInterval(null)
                return
            case 'testAccounts':
                setFilterTestAccounts(null)
                return
            case 'compare':
                setCompareFilter(null)
                return
        }
    }

    return (
        <>
            {activeFilters.map((active) => {
                const text = label(active)
                return (
                    <Chip
                        key={active.kind === 'property' ? `property-${active.index}` : active.kind}
                        size="default"
                        className="max-w-80"
                        data-attr={`dashboard-filter-chip-${active.kind}`}
                    >
                        <span className="truncate" title={text}>
                            {text}
                        </span>
                        <ChipClose
                            aria-label={`Remove ${text}`}
                            onClick={() => remove(active)}
                            data-attr="dashboard-filter-chip-remove"
                        />
                    </Chip>
                )
            })}
        </>
    )
}

import { useActions, useValues } from 'kea'

import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator } from '@posthog/quill'

import { TodayFilterMenuTrigger } from '~/layout/today/TodayFilterMenuTrigger'
import { TodayRecentRadioSubmenu } from '~/layout/today/TodayRecentRadioSubmenu'

import { CHECKS_FILTER_OPTIONS } from '../catalogTableRows'
import { DEFAULT_METRICS_FILTERS, MetricStatusFilter, metricsLogic } from '../metricsLogic'
import { DEFAULT_METRIC_CHECKS_FILTER, catalogMetricsLogic } from './catalogMetricsLogic'

const ANY_USER = 'any'
const ANY_USER_LABEL = 'Any user'

const STATUS_OPTIONS: { value: MetricStatusFilter; label: string }[] = [
    { value: 'all', label: 'All' },
    { value: 'proposed', label: 'Proposed' },
    { value: 'approved', label: 'Approved' },
]

export function CatalogMetricsFilterMenu(): JSX.Element {
    const { filters, ownerFilterOptions, creatorFilterOptions } = useValues(metricsLogic)
    const { setFilters } = useActions(metricsLogic)
    const { checksFilter } = useValues(catalogMetricsLogic)
    const { setChecksFilter } = useActions(catalogMetricsLogic)
    const filtersActive =
        filters.status !== DEFAULT_METRICS_FILTERS.status ||
        filters.createdBy !== null ||
        filters.owner !== null ||
        checksFilter !== DEFAULT_METRIC_CHECKS_FILTER

    const creatorOptions = [
        { value: ANY_USER, label: ANY_USER_LABEL },
        ...creatorFilterOptions.map((creator) => ({ value: creator.uuid, label: creator.label })),
    ]
    const ownerOptions = [
        { value: ANY_USER, label: ANY_USER_LABEL },
        ...ownerFilterOptions.map((owner) => ({ value: owner, label: owner })),
    ]

    return (
        <DropdownMenu>
            <TodayFilterMenuTrigger active={filtersActive} dataAttr="data-catalog-metrics-filter" />
            <DropdownMenuContent align="start" className="min-w-56">
                <TodayRecentRadioSubmenu
                    label="Status"
                    options={STATUS_OPTIONS}
                    value={filters.status}
                    defaultValue={DEFAULT_METRICS_FILTERS.status}
                    onChange={(status) => setFilters({ status })}
                    dataAttr="data-catalog-metrics-filter-status"
                />
                <TodayRecentRadioSubmenu
                    label="Created by"
                    options={creatorOptions}
                    value={filters.createdBy ?? ANY_USER}
                    defaultValue={ANY_USER}
                    onChange={(createdBy) => setFilters({ createdBy: createdBy === ANY_USER ? null : createdBy })}
                    dataAttr="data-catalog-metrics-filter-created-by"
                />
                <TodayRecentRadioSubmenu
                    label="Owner"
                    options={ownerOptions}
                    value={filters.owner ?? ANY_USER}
                    defaultValue={ANY_USER}
                    onChange={(owner) => setFilters({ owner: owner === ANY_USER ? null : owner })}
                    dataAttr="data-catalog-metrics-owner-filter"
                />
                <TodayRecentRadioSubmenu
                    label="Checks"
                    options={CHECKS_FILTER_OPTIONS}
                    value={checksFilter}
                    defaultValue={DEFAULT_METRIC_CHECKS_FILTER}
                    onChange={setChecksFilter}
                    dataAttr="data-catalog-metrics-filter-checks"
                />
                {filtersActive && (
                    <>
                        <DropdownMenuSeparator />
                        <DropdownMenuItem
                            variant="destructive"
                            onClick={() => {
                                setFilters({
                                    status: DEFAULT_METRICS_FILTERS.status,
                                    createdBy: DEFAULT_METRICS_FILTERS.createdBy,
                                    owner: DEFAULT_METRICS_FILTERS.owner,
                                })
                                setChecksFilter(DEFAULT_METRIC_CHECKS_FILTER)
                            }}
                            data-attr="data-catalog-metrics-filter-clear"
                        >
                            Clear filters
                        </DropdownMenuItem>
                    </>
                )}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}

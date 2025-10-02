import { useActions, useValues } from 'kea'

import { IconCollapse, IconExpand, IconInfo } from '@posthog/icons'
import { LemonBadge, LemonButton, LemonSelect, Tooltip } from '@posthog/lemon-ui'

import { humanizeActivity, humanizeScope } from 'lib/components/ActivityLog/humanizeActivity'
import { AnimatedCollapsible } from 'lib/components/AnimatedCollapsible'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'

import { ActivityScope } from '~/types'

import { DetailFilters } from './DetailFilters'
import { advancedActivityLogsLogic } from './advancedActivityLogsLogic'

export const BasicFiltersTab = (): JSX.Element => {
    const { filters, availableFilters, showMoreFilters, activeAdvancedFiltersCount } =
        useValues(advancedActivityLogsLogic)
    const { setFilters, setShowMoreFilters } = useActions(advancedActivityLogsLogic)

    return (
        <div className="flex flex-col gap-4 pt-4">
            <div className="flex gap-4 flex-start flex-wrap">
                <div className="flex flex-col gap-1">
                    <label className="block text-sm font-medium mb-1">Date range</label>
                    <DateFilter
                        dateFrom={filters.start_date}
                        dateTo={filters.end_date}
                        onChange={(start_date, end_date) => {
                            setFilters({ start_date: start_date || undefined, end_date: end_date || undefined })
                        }}
                        placeholder="All time"
                        data-attr="audit-logs-date-filter"
                        className="h-[24px] flex items-center"
                    />
                </div>

                <div className="flex flex-col gap-1">
                    <label className="block text-sm font-medium mb-1">User</label>
                    <LemonInputSelect
                        mode="multiple"
                        displayMode="count"
                        bulkActions="select-and-clear-all"
                        value={filters.users || []}
                        onChange={(users) => setFilters({ users })}
                        options={
                            availableFilters?.static_filters?.users?.map((u: any) => ({
                                key: u.value,
                                label: u.label,
                            })) || []
                        }
                        placeholder="All users"
                        allowCustomValues={false}
                        data-attr="audit-logs-user-filter"
                        size="small"
                        className="min-w-50"
                    />
                </div>

                <div className="flex flex-col gap-1">
                    <label className="block text-sm font-medium mb-1">Scope</label>
                    <LemonInputSelect
                        mode="multiple"
                        displayMode="count"
                        bulkActions="select-and-clear-all"
                        value={filters.scopes || []}
                        onChange={(scopes) => setFilters({ scopes: scopes as ActivityScope[] })}
                        options={
                            availableFilters?.static_filters?.scopes?.map((s: any) => ({
                                key: s.value,
                                label: humanizeScope(s.value, true),
                            })) || []
                        }
                        placeholder="All scopes"
                        allowCustomValues={false}
                        data-attr="audit-logs-scope-filter"
                        size="small"
                        className="min-w-50"
                    />
                </div>

                <div className="flex flex-col gap-1">
                    <label className="block text-sm font-medium mb-1">Activity</label>
                    <LemonInputSelect
                        mode="multiple"
                        displayMode="count"
                        bulkActions="select-and-clear-all"
                        value={filters.activities || []}
                        onChange={(activities) => setFilters({ activities })}
                        options={
                            availableFilters?.static_filters?.activities?.map((a: any) => ({
                                key: a.value,
                                label: humanizeActivity(a.value),
                            })) || []
                        }
                        placeholder="All activities"
                        allowCustomValues={false}
                        data-attr="audit-logs-action-filter"
                        size="small"
                        className="min-w-50"
                    />
                </div>

                <div className="flex items-end justify-end mb-1">
                    <div className="relative">
                        <LemonButton
                            type="tertiary"
                            size="small"
                            icon={showMoreFilters ? <IconCollapse /> : <IconExpand />}
                            onClick={() => setShowMoreFilters(!showMoreFilters)}
                            data-attr="audit-logs-more-filters-toggle"
                            className="text-muted-alt hover:text-default"
                        >
                            More filters
                        </LemonButton>
                        {!showMoreFilters && activeAdvancedFiltersCount > 0 && (
                            <LemonBadge
                                content={activeAdvancedFiltersCount.toString()}
                                size="small"
                                className="absolute -top-1 -right-1"
                            />
                        )}
                    </div>
                </div>
            </div>

            <AnimatedCollapsible collapsed={!showMoreFilters} autoHeight>
                <div className="border-t border-border mt-4 pt-4">
                    <div className="flex gap-4 flex-start flex-wrap pt-2">
                        <div className="flex flex-col gap-1">
                            <div className="flex items-center gap-1 mb-1">
                                <label className="block text-sm font-medium">Was impersonated?</label>
                                <Tooltip title="During support, PostHog team members may act as a specific user to help troubleshoot issues. These impersonated actions are logged and can be filtered here.">
                                    <IconInfo className="w-4 h-4 text-muted-alt cursor-help" />
                                </Tooltip>
                            </div>
                            <LemonSelect
                                value={
                                    filters.was_impersonated === undefined ? 'all' : filters.was_impersonated.toString()
                                }
                                onChange={(value) =>
                                    setFilters({ was_impersonated: value === 'all' ? undefined : value === 'true' })
                                }
                                options={[
                                    { value: 'all', label: 'All' },
                                    { value: 'true', label: 'Yes' },
                                    { value: 'false', label: 'No' },
                                ]}
                                placeholder="All"
                                data-attr="audit-logs-was-impersonated-filter"
                                size="small"
                                className="min-w-50"
                            />
                        </div>

                        <div className="flex flex-col gap-1">
                            <div className="flex items-center gap-1 mb-1">
                                <label className="block text-sm font-medium">Is system activity?</label>
                                <Tooltip title="Activities performed automatically by PostHog's system, such as scheduled tasks, background processes, or automated workflows.">
                                    <IconInfo className="w-4 h-4 text-muted-alt cursor-help" />
                                </Tooltip>
                            </div>
                            <LemonSelect
                                value={filters.is_system === undefined ? 'all' : filters.is_system.toString()}
                                onChange={(value) =>
                                    setFilters({ is_system: value === 'all' ? undefined : value === 'true' })
                                }
                                options={[
                                    { value: 'all', label: 'All' },
                                    { value: 'true', label: 'Yes' },
                                    { value: 'false', label: 'No' },
                                ]}
                                placeholder="All"
                                data-attr="audit-logs-is-system-filter"
                                size="small"
                                className="min-w-50"
                            />
                        </div>

                        <div className="flex flex-col gap-1">
                            <div className="flex items-center gap-1 mb-1">
                                <label className="block text-sm font-medium">Item IDs</label>
                                <Tooltip title="Filter by specific IDs of the items being tracked. Each activity log entry is associated with the ID of the object that was modified (e.g., dashboard ID, feature flag ID, etc.).">
                                    <IconInfo className="w-4 h-4 text-muted-alt cursor-help" />
                                </Tooltip>
                            </div>
                            <LemonInputSelect
                                mode="multiple"
                                displayMode="count"
                                bulkActions="select-and-clear-all"
                                value={filters.item_ids || []}
                                onChange={(item_ids) => setFilters({ item_ids })}
                                options={[]}
                                placeholder="Enter item IDs"
                                allowCustomValues={true}
                                data-attr="audit-logs-item-ids-filter"
                                size="small"
                                className="min-w-50"
                            />
                        </div>
                    </div>
                    <div className="py-4">
                        <DetailFilters />
                    </div>
                </div>
            </AnimatedCollapsible>
        </div>
    )
}

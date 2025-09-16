import { useActions, useValues } from 'kea'

import { humanizeActivity, humanizeScope } from 'lib/components/ActivityLog/humanizeActivity'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'

import { ActivityScope } from '~/types'

import { advancedActivityLogsLogic } from './advancedActivityLogsLogic'

export const BasicFiltersTab = (): JSX.Element => {
    const { filters, availableFilters } = useValues(advancedActivityLogsLogic)
    const { setFilters } = useActions(advancedActivityLogsLogic)

    return (
        <div className="flex gap-4 flex-start flex-wrap pt-4">
            <div className="flex flex-col gap-1">
                <label className="block text-sm font-medium mb-1">Date Range</label>
                <DateFilter
                    dateFrom={filters.start_date}
                    dateTo={filters.end_date}
                    onChange={(start_date, end_date) => {
                        setFilters({ start_date: start_date || undefined, end_date: end_date || undefined })
                    }}
                    placeholder="All time"
                    data-attr="audit-logs-date-filter"
                    className="h-8 flex items-center"
                />
            </div>

            <div className="flex flex-col gap-1">
                <label className="block text-sm font-medium mb-1">User</label>
                <LemonInputSelect
                    mode="multiple"
                    displayMode="snacks"
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
                    className="min-w-50 min-h-10"
                />
            </div>

            <div className="flex flex-col gap-1">
                <label className="block text-sm font-medium mb-1">Scope</label>
                <LemonInputSelect
                    mode="multiple"
                    displayMode="snacks"
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
                    className="min-w-50 min-h-10"
                />
            </div>

            <div className="flex flex-col gap-1">
                <label className="block text-sm font-medium mb-1">Action</label>
                <LemonInputSelect
                    mode="multiple"
                    displayMode="snacks"
                    bulkActions="select-and-clear-all"
                    value={filters.activities || []}
                    onChange={(activities) => setFilters({ activities })}
                    options={
                        availableFilters?.static_filters?.activities?.map((a: any) => ({
                            key: a.value,
                            label: humanizeActivity(a.value),
                        })) || []
                    }
                    placeholder="All actions"
                    allowCustomValues={false}
                    data-attr="audit-logs-action-filter"
                    className="min-w-50 min-h-10"
                />
            </div>
        </div>
    )
}

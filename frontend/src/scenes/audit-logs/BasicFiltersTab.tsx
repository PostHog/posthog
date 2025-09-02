import { useActions, useValues } from 'kea'

import { LemonSelect } from '@posthog/lemon-ui'

import { humanizeActivity, humanizeScope } from 'lib/components/ActivityLog/humanizeActivity'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'

import { ActivityScope } from '~/types'

import { advancedActivityLogsLogic } from './advancedActivityLogsLogic'

export const BasicFiltersTab = (): JSX.Element => {
    const { filters, availableFilters } = useValues(advancedActivityLogsLogic)
    const { setFilters } = useActions(advancedActivityLogsLogic)

    return (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 pt-4">
            <div>
                <label className="block text-sm font-medium mb-1">Date Range</label>
                <DateFilter
                    dateFrom={filters.start_date}
                    dateTo={filters.end_date}
                    onChange={(start_date, end_date) => {
                        setFilters({ start_date: start_date as string | null, end_date: end_date as string | null })
                    }}
                    placeholder="All time"
                />
            </div>

            <div>
                <label className="block text-sm font-medium mb-1">User</label>
                <LemonSelect
                    value={filters.users[0] || null}
                    onChange={(user) => setFilters({ users: user ? [user] : [] })}
                    options={
                        availableFilters?.static_filters?.users?.map((u) => ({ label: u.label, value: u.value })) || []
                    }
                    placeholder="All users"
                    allowClear
                />
            </div>

            <div>
                <label className="block text-sm font-medium mb-1">Scope</label>
                <LemonSelect
                    value={filters.scopes[0] || null}
                    onChange={(scope) => setFilters({ scopes: scope ? [scope as ActivityScope] : [] })}
                    options={
                        availableFilters?.static_filters?.scopes?.map((s) => ({
                            label: humanizeScope(s.value, true),
                            value: s.value,
                        })) || []
                    }
                    placeholder="All scopes"
                    allowClear
                />
            </div>

            <div>
                <label className="block text-sm font-medium mb-1">Action</label>
                <LemonSelect
                    value={filters.activities[0] || null}
                    onChange={(activity) => setFilters({ activities: activity ? [activity] : [] })}
                    options={
                        availableFilters?.static_filters?.activities?.map((a) => ({
                            label: humanizeActivity(a.value),
                            value: a.value,
                        })) || []
                    }
                    placeholder="All actions"
                    allowClear
                />
            </div>
        </div>
    )
}

import { useActions, useValues } from 'kea'

import { LemonInput } from '@posthog/lemon-ui'

import { MemberSelect } from 'lib/components/MemberSelect'

import { alertsLogic } from './alertsLogic'

export function AlertsFiltersBar(): JSX.Element {
    const { filters } = useValues(alertsLogic)
    const { setFilters } = useActions(alertsLogic)

    return (
        <div className="flex justify-between gap-2 flex-wrap mb-4">
            <LemonInput
                type="search"
                placeholder="Search for alerts"
                onChange={(value) => setFilters({ search: value })}
                value={filters.search}
            />
            <div className="flex items-center gap-2">
                <span>Created by:</span>
                <MemberSelect
                    value={filters.createdBy === 'All users' ? null : filters.createdBy}
                    onChange={(user) => setFilters({ createdBy: user?.uuid || 'All users' })}
                />
            </div>
        </div>
    )
}

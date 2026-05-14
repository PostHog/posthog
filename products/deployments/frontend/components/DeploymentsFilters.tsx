import { useActions, useValues } from 'kea'

import { LemonInput, LemonInputSelect, LemonSelect } from '@posthog/lemon-ui'

import { deploymentsLogic } from '../deploymentsLogic'
import { DeploymentStatus } from '../fixtures'

const STATUS_OPTIONS: { label: string; key: DeploymentStatus }[] = [
    { label: 'Ready', key: 'ready' },
    { label: 'Error', key: 'error' },
    { label: 'Building', key: 'building' },
    { label: 'Queued', key: 'queued' },
    { label: 'Initializing', key: 'initializing' },
    { label: 'Cancelled', key: 'cancelled' },
]

export function DeploymentsFilters(): JSX.Element {
    const { filters, authorOptions } = useValues(deploymentsLogic)
    const { setFilters } = useActions(deploymentsLogic)

    return (
        <div className="flex flex-wrap items-center gap-2">
            <LemonInput
                type="search"
                placeholder="Search by commit, branch, or id"
                value={filters.search}
                onChange={(search) => setFilters({ search, page: 1 })}
                className="min-w-64"
            />
            <div className="w-64">
                <LemonInputSelect
                    mode="multiple"
                    placeholder="Status"
                    options={STATUS_OPTIONS}
                    value={filters.status}
                    onChange={(status) => setFilters({ status: status as DeploymentStatus[], page: 1 })}
                    allowCustomValues={false}
                    autoWidth={false}
                />
            </div>
            <div className="w-64">
                {/* Backend supports a single `author` query param (icontains on email).
                    LemonSelect is the right single-value picker; users can clear to "Any author". */}
                <LemonSelect
                    placeholder="Any author"
                    options={[
                        { value: null as unknown as string, label: 'Any author' },
                        ...authorOptions.map((o) => ({ value: o.value, label: o.label })),
                    ]}
                    value={filters.author}
                    onChange={(author) => setFilters({ author: author ?? null, page: 1 })}
                    allowClear
                />
            </div>
        </div>
    )
}

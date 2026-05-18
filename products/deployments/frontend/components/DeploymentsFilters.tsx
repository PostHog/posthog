import { useActions, useValues } from 'kea'

import { LemonInput, LemonInputSelect } from '@posthog/lemon-ui'

import { deploymentProjectLogic } from '../deploymentProjectLogic'
import { DeploymentStatus } from '../fixtures'

const STATUS_OPTIONS: { label: string; key: DeploymentStatus }[] = [
    { label: 'Ready', key: 'ready' },
    { label: 'Error', key: 'error' },
    { label: 'Building', key: 'building' },
    { label: 'Queued', key: 'queued' },
    { label: 'Initializing', key: 'initializing' },
    { label: 'Cancelled', key: 'cancelled' },
]

export function DeploymentsFilters({ projectId }: { projectId: string }): JSX.Element {
    const { filters } = useValues(deploymentProjectLogic({ projectId }))
    const { setFilters } = useActions(deploymentProjectLogic({ projectId }))

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
            {/* Free-text input: the backend matches `author` against
                `commit_author_email` (iexact). A dropdown built from the
                current page would silently hide authors who only appear on
                other pages and shift its option list as filters narrow the
                result set, so we accept the small typing cost for a stable,
                complete filter. */}
            <LemonInput
                type="search"
                placeholder="Filter by author email"
                value={filters.author ?? ''}
                onChange={(author) => setFilters({ author: author || null, page: 1 })}
                className="w-64"
            />
        </div>
    )
}

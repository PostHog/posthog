import { useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'
import { DataNode, TracesQuery } from '@posthog/query-frontend/schema/schema-general'
import { isTracesQuery } from '@posthog/query-frontend/utils'

import { userLogic } from 'scenes/userLogic'

interface SupportTracesFiltersProps {
    query: DataNode
    setQuery?: (query: TracesQuery) => void
}

export function SupportTracesFilters({ query, setQuery }: SupportTracesFiltersProps): JSX.Element | null {
    const { user } = useValues(userLogic)

    // Only show for impersonating users (support agents)
    if (!user?.is_impersonated) {
        return null
    }

    if (!isTracesQuery(query)) {
        return null
    }

    // showSupportTraces is the inverse of filterSupportTraces
    // Default: filterSupportTraces=false for impersonated users, so showSupportTraces=true
    const showSupportTraces = !(query.filterSupportTraces ?? false)

    return (
        <LemonSwitch
            id="support-traces-filter"
            bordered
            checked={showSupportTraces}
            onChange={(checked: boolean) => {
                const newQuery: TracesQuery = {
                    ...query,
                    filterSupportTraces: !checked,
                }
                setQuery?.(newQuery)
            }}
            label="Show support traces"
        />
    )
}

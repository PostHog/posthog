import { useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { userLogic } from 'scenes/userLogic'

import { DataNode, TracesQuery } from '~/queries/schema/schema-general'
import { isTracesQuery } from '~/queries/utils'

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

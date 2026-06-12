import { IconInfo } from '@posthog/icons'
import { useDebouncedQuery } from '@posthog/query-frontend/hooks/useDebouncedQuery'
import { GroupsQuery } from '@posthog/query-frontend/schema/schema-general'

import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

interface GroupsSearchProps {
    query: GroupsQuery
    setQuery?: (query: GroupsQuery) => void
    groupTypeLabel?: string
}

export function GroupsSearch({ query, setQuery, groupTypeLabel = 'groups' }: GroupsSearchProps): JSX.Element {
    const { value, onChange } = useDebouncedQuery<GroupsQuery, string>(
        query,
        setQuery,
        (query) => query.search || '',
        (query, value) => ({ ...query, search: value })
    )

    return (
        <div className="flex items-center gap-2">
            <LemonInput
                type="search"
                value={value}
                placeholder={`Search for ${groupTypeLabel}`}
                data-attr="groups-search"
                disabled={!setQuery}
                onChange={onChange}
            />
            <Tooltip title="Search by name or identifier">
                <IconInfo className="text-2xl text-secondary shrink-0" />
            </Tooltip>
        </div>
    )
}

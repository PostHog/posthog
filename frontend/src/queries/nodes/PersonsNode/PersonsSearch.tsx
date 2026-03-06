import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'

import { useDebouncedQuery } from '~/queries/hooks/useDebouncedQuery'
import { ActorsQuery, PersonsNode } from '~/queries/schema/schema-general'
import { isQueryForGroup } from '~/queries/utils'

type ActorType = 'person' | 'group'
interface PersonSearchProps {
    query: PersonsNode | ActorsQuery
    setQuery?: (query: PersonsNode | ActorsQuery) => void
}

const placeholders: Record<ActorType, string> = {
    person: 'Search by name, email, Person ID or Distinct ID',
    group: 'Search by group name or Distinct ID (group name matches partially, Distinct ID must match exactly)',
}

export function PersonsSearch({ query, setQuery }: PersonSearchProps): JSX.Element {
    const { value, onChange } = useDebouncedQuery<PersonsNode | ActorsQuery, string>(
        query,
        setQuery,
        (query) => query.search || '',
        (query, value) => ({ ...query, search: value })
    )
    const target: ActorType = isQueryForGroup(query) ? 'group' : 'person'

    return (
        <div className="flex items-center flex-1 min-w-0">
            <LemonInput
                type="search"
                value={value ?? ''}
                placeholder={placeholders[target]}
                data-attr="persons-search"
                disabled={!setQuery}
                onChange={onChange}
                fullWidth
            />
        </div>
    )
}

import { IconInfo } from '@posthog/icons'

import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { useDebouncedQuery } from '~/queries/hooks/useDebouncedQuery'
import { ActorsQuery, PersonsNode } from '~/queries/schema/schema-general'
import { isQueryForGroup } from '~/queries/utils'

type ActorType = 'person' | 'group'
interface PersonSearchProps {
    query: PersonsNode | ActorsQuery
    setQuery?: (query: PersonsNode | ActorsQuery) => void
}

interface LabelType {
    label: string
    description: string
}

const labels: Record<ActorType, LabelType> = {
    person: {
        label: 'persons',
        description: 'Search by name, email, Person ID or Distinct ID.',
    },
    group: {
        label: 'groups',
        description:
            'Search by group name or Distinct ID. Group name will match partially. Distinct ID needs to match exactly.',
    },
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
        <div className="flex items-center gap-2">
            <LemonInput
                type="search"
                value={value ?? ''}
                placeholder={`Search for ${labels[target].label}`}
                data-attr="persons-search"
                disabled={!setQuery}
                onChange={onChange}
            />
            <Tooltip title={labels[target].description}>
                <IconInfo className="text-2xl text-secondary shrink-0" />
            </Tooltip>
        </div>
    )
}

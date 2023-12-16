import { IconInfo } from 'lib/lemon-ui/icons'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { useDebouncedQuery } from '~/queries/hooks/useDebouncedQuery'
import { PersonsNode, PersonsQuery } from '~/queries/schema'
import { isInsightPersonsQuery, isPersonsQuery, isRetentionQuery } from '~/queries/utils'

interface PersonSearchProps {
    query: PersonsNode | PersonsQuery
    setQuery?: (query: PersonsNode | PersonsQuery) => void
}

type actorType = 'person' | 'group'

const labels: Record<actorType, any> = {
    person: {
        label: 'persons',
        description:
            'Search by email or Distinct ID. Email will match partially, for example: "@gmail.com". Distinct ID needs to match exactly.',
    },
    group: {
        label: 'groups',
        description:
            'Search by group name or Distinct ID. Group name will match partially. Distinct ID needs to match exactly.',
    },
}

function queryForGroup(query: PersonsNode | PersonsQuery): boolean {
    return (
        isPersonsQuery(query) &&
        isInsightPersonsQuery(query.source) &&
        isRetentionQuery(query.source.source) &&
        query.source.source.aggregation_group_type_index !== undefined
    )
}

export function PersonsSearch({ query, setQuery }: PersonSearchProps): JSX.Element {
    const { value, onChange } = useDebouncedQuery<PersonsNode | PersonsQuery, string>(
        query,
        setQuery,
        (query) => query.search || '',
        (query, value) => ({ ...query, search: value })
    )
    const target: actorType = queryForGroup(query) ? 'group' : 'person'

    return (
        <div className="flex items-center gap-2">
            <LemonInput
                type="search"
                value={value}
                placeholder={`Search for ${labels[target].label}`}
                data-attr="persons-search"
                disabled={!setQuery}
                onChange={onChange}
            />
            <Tooltip title={<>{labels[target].description}</>}>
                <IconInfo className="text-2xl text-muted-alt shrink-0" />
            </Tooltip>
        </div>
    )
}

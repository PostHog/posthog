import { PersonsNode, PersonsQuery } from '~/queries/schema'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { IconInfo } from 'lib/lemon-ui/icons'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { useDebouncedQuery } from '~/queries/hooks/useDebouncedQuery'

interface PersonSearchProps {
    query: PersonsNode | PersonsQuery
    setQuery?: (query: PersonsNode | PersonsQuery) => void
}

export function PersonsSearch({ query, setQuery }: PersonSearchProps): JSX.Element {
    const { value, onChange } = useDebouncedQuery<PersonsNode | PersonsQuery, string>(
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
                placeholder="Search for persons"
                data-attr="persons-search"
                disabled={!setQuery}
                onChange={onChange}
            />
            <Tooltip
                title={
                    <>
                        Search by email or Distinct ID. Email will match partially, for example: "@gmail.com". Distinct
                        ID needs to match exactly.
                    </>
                }
            >
                <IconInfo className="text-2xl text-muted-alt shrink-0" />
            </Tooltip>
        </div>
    )
}

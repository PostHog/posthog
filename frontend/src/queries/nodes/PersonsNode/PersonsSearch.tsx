import { PersonsNode } from '~/queries/schema'
import { LemonInput } from 'lib/components/LemonInput/LemonInput'
import { IconInfo } from 'lib/components/icons'
import { Tooltip } from 'lib/components/Tooltip'

interface PersonSearchProps {
    query: PersonsNode
    setQuery?: (node: PersonsNode) => void
}

export function PersonsSearch({ query, setQuery }: PersonSearchProps): JSX.Element {
    return (
        <div className="flex items-center gap-2">
            <LemonInput
                type="search"
                value={query.search ?? ''}
                placeholder="Search for persons"
                data-attr="persons-search"
                disabled={!setQuery}
                onChange={(value: string) => setQuery?.({ ...query, search: value })}
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

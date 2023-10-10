import { useValues, useActions } from 'kea'

import { LemonInput } from '@posthog/lemon-ui'
import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'

import { searchBarLogic } from './searchBarLogic'
import SearchBarTab from './SearchBarTab'
import { ResultTypesWithAll } from './types'

const SearchBar = (): JSX.Element => {
    const { searchQuery, searchResults } = useValues(searchBarLogic)
    const { setSearchQuery } = useActions(searchBarLogic)
    const activeTab: ResultTypesWithAll = 'all'
    return (
        <div className="flex flex-col h-full">
            <div className="border-b">
                <LemonInput
                    type="search"
                    size="small"
                    className="command-bar__search-input"
                    fullWidth
                    suffix={<KeyboardShortcut escape muted />}
                    autoFocus
                    value={searchQuery}
                    onChange={setSearchQuery}
                />
            </div>
            <div className="grow">
                {searchResults.results?.map((r) => (
                    <div key={`${r.type}_${r.pk}`}>{JSON.stringify(r, null, 2)}</div>
                ))}
            </div>
            {searchResults.counts && (
                <div className="flex items-center border-t">
                    <SearchBarTab type="all" isFirst active={activeTab === 'all'} />
                    {Object.entries(searchResults.counts).map(([type, count]) => (
                        <SearchBarTab key={type} type={type} count={count} active={activeTab === type} />
                    ))}
                </div>
            )}
        </div>
    )
}

export default SearchBar

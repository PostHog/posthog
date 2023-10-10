import { useValues, useActions } from 'kea'

import { LemonInput } from '@posthog/lemon-ui'
import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'

import { searchBarLogic } from './searchBarLogic'

const SearchBar = (): JSX.Element => {
    const { searchQuery, searchResults } = useValues(searchBarLogic)
    const { setSearchQuery } = useActions(searchBarLogic)
    return (
        <div>
            <div className="border-b">
                <LemonInput
                    type="search"
                    className="command-bar__search-input"
                    fullWidth
                    suffix={<KeyboardShortcut escape muted />}
                    autoFocus
                    value={searchQuery}
                    onChange={setSearchQuery}
                />
            </div>
            <div>
                {searchResults.results?.map((r) => (
                    <div key={`${r.type}_${r.pk}`}>{JSON.stringify(r, null, 2)}</div>
                ))}
            </div>
            {searchResults.counts && (
                <div>
                    {Object.entries(searchResults.counts).map(([k, v]) => {
                        return (
                            <span key={k}>
                                {k}: {v}
                            </span>
                        )
                    })}
                </div>
            )}
        </div>
    )
}

export default SearchBar

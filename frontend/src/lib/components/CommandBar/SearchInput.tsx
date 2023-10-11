import { useActions, useValues } from 'kea'

import { LemonInput } from '@posthog/lemon-ui'
import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'

import { searchBarLogic } from './searchBarLogic'

const SearchInput = (): JSX.Element => {
    const { searchQuery } = useValues(searchBarLogic)
    const { setSearchQuery } = useActions(searchBarLogic)

    return (
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
    )
}

export default SearchInput

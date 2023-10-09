import { LemonInput } from '@posthog/lemon-ui'
import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'

const SearchBar = (): JSX.Element => {
    return (
        <div className="border-b">
            <LemonInput
                type="search"
                className="command-bar__search-input"
                fullWidth
                suffix={<KeyboardShortcut escape muted />}
                autoFocus
            />
        </div>
    )
}

export default SearchBar

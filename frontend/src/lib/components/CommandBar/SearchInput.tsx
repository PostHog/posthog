import { useActions, useValues } from 'kea'
import { Ref, forwardRef } from 'react'

import { LemonInput } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'

import { searchBarLogic } from './searchBarLogic'

export const SearchInput = forwardRef(function SearchInput(_, ref: Ref<HTMLInputElement>): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { searchQuery } = useValues(searchBarLogic)
    const { setSearchQuery } = useActions(searchBarLogic)

    const placeholder = `Search ${currentTeam ? 'the ' + currentTeam.name : 'this'} project… or enter > for commands`

    return (
        <div className="border-b">
            <LemonInput
                data-attr="search-bar-input"
                inputRef={ref}
                type="search"
                className="CommandBar__input"
                fullWidth
                suffix={<KeyboardShortcut escape />}
                placeholder={placeholder}
                autoFocus
                value={searchQuery}
                onChange={setSearchQuery}
            />
        </div>
    )
})

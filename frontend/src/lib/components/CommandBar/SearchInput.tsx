import { LemonButton, LemonInput } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { isMac } from 'lib/utils'
import { forwardRef, Ref } from 'react'
import { teamLogic } from 'scenes/teamLogic'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'

import { searchBarLogic } from './searchBarLogic'

export const SearchInput = forwardRef(function _SearchInput(_, ref: Ref<HTMLInputElement>): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { searchQuery } = useValues(searchBarLogic)
    const { setSearchQuery, hideCommandBar } = useActions(searchBarLogic)

    const modifierKey = isMac() ? '⌘' : '^'
    const placeholder = currentTeam
        ? `Search the ${currentTeam.name} project or press ${modifierKey}⇧K to go to commands…`
        : `Search or press ${modifierKey}⇧K to go to commands…`

    return (
        <div className="border-b">
            <LemonInput
                ref={ref}
                type="search"
                className="CommandBar__input"
                fullWidth
                suffix={
                    <LemonButton onClick={() => hideCommandBar()} noPadding>
                        <KeyboardShortcut escape />
                    </LemonButton>
                }
                placeholder={placeholder}
                autoFocus
                value={searchQuery}
                onChange={setSearchQuery}
            />
        </div>
    )
})

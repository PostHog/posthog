import { useActions, useValues } from 'kea'

import { LemonInput } from '@posthog/lemon-ui'
import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'

import { searchBarLogic } from './searchBarLogic'
import { forwardRef, Ref } from 'react'

export const SearchInput = forwardRef(function _SearchInput(_, ref: Ref<HTMLInputElement>): JSX.Element {
    const { searchQuery } = useValues(searchBarLogic)
    const { setSearchQuery } = useActions(searchBarLogic)

    return (
        <div className="border-b">
            <LemonInput
                ref={ref}
                type="search"
                size="small"
                className="CommandBar__input"
                fullWidth
                suffix={<KeyboardShortcut escape muted />}
                autoFocus
                value={searchQuery}
                onChange={setSearchQuery}
            />
        </div>
    )
})

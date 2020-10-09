import React, { useCallback } from 'react'
import { SearchOutlined } from '@ant-design/icons'
import { useValues, useActions } from 'kea'
import { commandLogic } from './commandLogic'
import { CommandInputContainer, CommandInputElement } from './commandStyledComponents'

export function CommandInput(): JSX.Element {
    const { searchInput } = useValues(commandLogic)
    const { setSearchInput, hidePalette } = useActions(commandLogic)

    const handleKeyDown = useCallback(
        (event: KeyboardEvent): void => {
            if (event.key === 'Escape') {
                event.preventDefault()
                if (searchInput) setSearchInput('')
                // At first, only erase input
                else hidePalette() // Then hide palette
            } else if (event.key === 'k' && (event.ctrlKey || event.metaKey)) hidePalette()
        },
        [searchInput, hidePalette]
    )

    return (
        <CommandInputContainer style={{ padding: '0 2rem' }}>
            <SearchOutlined />
            <CommandInputElement
                autoFocus
                value={searchInput}
                onKeyDown={handleKeyDown}
                onChange={(event) => {
                    setSearchInput(event.target.value)
                }}
                placeholder="What would you like to do? Try some suggestions…"
            />
        </CommandInputContainer>
    )
}

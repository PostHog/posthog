import React, { useCallback } from 'react'
import { SearchOutlined } from '@ant-design/icons'
import { useValues, useActions } from 'kea'
import { commandLogic } from './commandLogic'
import { CommandInputContainer, CommandInputElement } from './shared'
import { useEventListener } from 'lib/hooks/useEventListener'
import squeak from './../../../../public/squeak.mp3'
import PHicon from './../../../../public/icon-white.svg'

export function CommandInput(): JSX.Element {
    const { searchInput } = useValues(commandLogic)
    const { setSearchInput, hidePalette } = useActions(commandLogic)
    const audio = new Audio(squeak)

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

    const handleEnterDown = useCallback(
        (event: KeyboardEvent) => {
            if (event.key === 'Enter' && searchInput === 'squeak') {
                audio.play()
            }
        },
        [searchInput, audio]
    )

    useEventListener('keydown', handleEnterDown)

    return (
        <CommandInputContainer style={{ padding: '0 2rem' }}>
            {searchInput === 'squeak' ? <img src={PHicon} style={{ width: '1rem' }}></img> : <SearchOutlined />}
            <CommandInputElement
                autoFocus
                value={searchInput}
                onKeyDown={handleKeyDown}
                onChange={(event) => {
                    setSearchInput(event.target.value)
                }}
                placeholder="What would you like to do?"
            />
        </CommandInputContainer>
    )
}

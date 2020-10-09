import React, { useCallback } from 'react'
import styled from 'styled-components'
import { SearchOutlined } from '@ant-design/icons'
import { useValues, useActions } from 'kea'
import { commandLogic } from './commandLogic'

const CommandInputContainer = styled.div`
    display: flex;
    align-items: center;
    height: 4rem;
    padding: 0 2rem;
    border: none;
    outline: none;
    background: transparent;
    color: #fff;
    font-size: 1rem;
    line-height: 4rem;
    overflow-y: scroll;
`

const CommandInputElement = styled.input`
    flex-grow: 1;
    height: 4rem;
    padding-left: 1rem;
    border: none;
    outline: none;
    background: transparent;
    color: #fff;
    font-size: 1rem;
    line-height: 4rem;
    overflow-y: scroll;
`

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
        <CommandInputContainer>
            <SearchOutlined />
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

import React, { Dispatch, SetStateAction, useCallback } from 'react'
import styled from 'styled-components'

const CommandInputElement = styled.input`
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

interface Props {
    input: string
    setInput: Dispatch<SetStateAction<string>>
    setIsPaletteShown: Dispatch<SetStateAction<boolean>>
}

export function CommandInput({ input, setInput, setIsPaletteShown }: Props): JSX.Element {
    const handleKeyDown = useCallback(
        (event: KeyboardEvent): void => {
            if (event.key === 'Escape') {
                event.preventDefault()
                if (input) setInput('')
                // At first, only erase input
                else setIsPaletteShown(false) // Then hide palette
            } else if (event.key === 'k' && (event.ctrlKey || event.metaKey)) setIsPaletteShown(false)
        },
        [input, setInput]
    )

    return (
        <CommandInputElement
            autoFocus
            value={input}
            onKeyDown={handleKeyDown}
            onChange={(event) => {
                setInput(event.target.value)
            }}
            placeholder="What would you like to do?"
        />
    )
}

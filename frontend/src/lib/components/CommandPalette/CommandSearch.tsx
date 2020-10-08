import React, { Dispatch, SetStateAction, useCallback } from 'react'
import styled from 'styled-components'

const CommandInput = styled.input`
    overflow-y: scroll;
`

interface Props {
    input: string
    setInput: Dispatch<SetStateAction<string>>
    setIsPaletteShown: Dispatch<SetStateAction<boolean>>
}

export function CommandSearch({ input, setInput, setIsPaletteShown }: Props): JSX.Element {
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
        <CommandInput
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

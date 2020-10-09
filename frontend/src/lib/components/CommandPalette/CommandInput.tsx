import React, { Dispatch, SetStateAction, useCallback } from 'react'
import { SearchOutlined } from '@ant-design/icons'
import { CommandInputContainer, CommandInputElement } from './shared'

interface Props {
    input: string
    setInput: (input: string) => void
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
        <CommandInputContainer style={{ padding: '0 2rem' }}>
            <SearchOutlined />
            <CommandInputElement
                autoFocus
                value={input}
                onKeyDown={handleKeyDown}
                onChange={(event) => {
                    setInput(event.target.value)
                }}
                placeholder="What would you like to do?"
            />
        </CommandInputContainer>
    )
}

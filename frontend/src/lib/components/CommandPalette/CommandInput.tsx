import React, { Dispatch, SetStateAction, useCallback } from 'react'
import styled from 'styled-components'
import { EditOutlined } from '@ant-design/icons'

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
        <CommandInputContainer>
            <EditOutlined />
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

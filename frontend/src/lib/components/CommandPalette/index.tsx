import React, { useState, useRef, useCallback, useEffect } from 'react'
import { useOutsideClickHandler } from 'lib/utils'
import { useHotkeys } from 'react-hotkeys-hook'
import { useMountedLogic, useValues, useActions } from 'kea'
import { commandLogic } from './commandLogic'
import { CommandInput } from './CommandInput'
import { CommandResults } from './CommandResults'
import styled from 'styled-components'
import { userLogic } from 'scenes/userLogic'

const CommandPaletteContainer = styled.div`
    position: absolute;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    display: flex;
    flex-direction: column;
    align-items: center;
`

const CommandPaletteBox = styled.div`
    position: fixed;
    top: 30%;
    display: flex;
    flex-direction: column;
    z-index: 9999;
    width: 36rem;
    max-height: 60%;
    overflow: hidden;
`

export function CommandPalette(): JSX.Element | null {
    useMountedLogic(commandLogic)

    const { setSearchInput: setInput } = useActions(commandLogic)
    const { searchInput: input, commandSearchResults } = useValues(commandLogic)
    const { user } = useValues(userLogic)

    const [isPaletteShown, setIsPaletteShown] = useState(false)

    const boxRef = useRef<HTMLDivElement | null>(null)

    const toggleIsPaletteShown = useCallback(() => {
        setIsPaletteShown(!isPaletteShown)
    }, [setIsPaletteShown, isPaletteShown])

    useHotkeys('cmd+k,ctrl+k', toggleIsPaletteShown)

    useHotkeys('esc', () => {
        setIsPaletteShown(false)
    })

    useOutsideClickHandler(boxRef, () => {
        setIsPaletteShown(false)
    })

    useEffect(() => {
        // prevent scrolling when box is open
        document.body.style.overflow = isPaletteShown ? 'hidden' : ''
    }, [isPaletteShown])

    return (
        <>
            {!user || !isPaletteShown ? null : (
                <CommandPaletteContainer>
                    <CommandPaletteBox ref={boxRef} className="card bg-dark">
                        <CommandInput setIsPaletteShown={setIsPaletteShown} input={input} setInput={setInput} />
                        <CommandResults
                            results={commandSearchResults}
                            setIsPaletteShown={setIsPaletteShown}
                            isPaletteShown={isPaletteShown}
                            setInput={setInput}
                        />
                    </CommandPaletteBox>
                </CommandPaletteContainer>
            )}
        </>
    )
}

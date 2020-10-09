import React, { useState, useRef } from 'react'
import { useOutsideClickHandler } from 'lib/utils'
import { useHotkeys } from 'react-hotkeys-hook'
import { useMountedLogic, useValues, useActions } from 'kea'
import { commandLogic } from './commandLogic'
import { CommandInput } from './CommandInput'
import { CommandResults } from './CommandResults'
import styled from 'styled-components'
import { userLogic } from 'scenes/userLogic'
import { useCallback } from 'react'

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
    width: 32rem;
    max-height: 60%;
    overflow: hidden;
`

/*const Scope = styled.div`
    background-color: #4d4d4d;
    height: 22px;
    width: 100%;
    padding-left: 16px;
    padding-right: 16px;
    text-transform: uppercase;
    color: rgba(255, 255, 255, 0.8);
    font-weight: bold;
`*/

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

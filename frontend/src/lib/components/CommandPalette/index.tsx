import React, { useRef } from 'react'
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
    pointer-events: none;
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

    const { hidePalette, togglePalette } = useActions(commandLogic)
    const { isPaletteShown } = useValues(commandLogic)
    const { user } = useValues(userLogic)

    const boxRef = useRef<HTMLDivElement | null>(null)

    useHotkeys('cmd+k,ctrl+k', togglePalette)

    useHotkeys('esc', hidePalette)

    useOutsideClickHandler(boxRef, hidePalette)

    return (
        <>
            {!user || !isPaletteShown ? null : (
                <CommandPaletteContainer>
                    <CommandPaletteBox ref={boxRef} className="card bg-dark">
                        <CommandInput />
                        <CommandResults />
                    </CommandPaletteBox>
                </CommandPaletteContainer>
            )}
        </>
    )
}

import { useOutsideClickHandler } from 'lib/utils'
import React, { useEffect } from 'react'
import { useRef } from 'react'
import { useHotkeys } from 'react-hotkeys-hook'
import { useCommands } from './commandLogic'
import { globalCommands } from './globalCommands'
import { CommandSearch } from './CommandSearch'
import { CommandResult } from './CommandResult'
import styled from 'styled-components'
import { DashboardFilled } from '@ant-design/icons'

const PaletteContainer = styled.div`
    z-index: 9999;
    position: absolute;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    width: 700px;
    min-height: 200px;
    max-height: 60%;
    box-shadow: 1px 4px 6px rgba(0, 0, 0, 0.1);
    background-color: #373737;
    border-radius: 10px;
    display: flex;
    flex-direction: column;
`

const ResultsContainer = styled.div`
    overflow-y: scroll;
    padding-top: 8px;
`

interface BoxProps {
    visible: boolean
    onClickOutside: () => void
    onClose: () => void
}

export function CommandPalette({ visible, onClose }: BoxProps): JSX.Element | false {
    const boxRef = useRef<HTMLDivElement | null>(null)

    useHotkeys('esc', () => {
        onClose()
    })

    useOutsideClickHandler(boxRef, () => {
        onClose()
    })

    useCommands(globalCommands)

    useEffect(() => {
        // prevent scrolling when box is open
        document.body.style.overflow = visible ? 'hidden' : ''
    }, [visible])

    return (
        visible && (
            <PaletteContainer ref={boxRef}>
                <CommandSearch onClose={onClose}></CommandSearch>
                <ResultsContainer>
                    <CommandResult Icon={DashboardFilled} text="go to dashboard AARRR" />
                </ResultsContainer>
            </PaletteContainer>
        )
    )
}

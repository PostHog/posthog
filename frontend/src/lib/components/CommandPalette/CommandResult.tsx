import { useActions } from 'kea'
import React, { useCallback } from 'react'
import styled from 'styled-components'
import { router } from 'kea-router'
import { Command, CommandExecutor, CommandResult as CommandResultType } from './commandLogic'

interface ContainerProps {
    focused?: boolean
    isHint?: boolean
    onClick?: CommandExecutor
}

const ResultContainer = styled.div<ContainerProps>`
    height: 60px;
    width: 100%;
    padding-left: 32px;
    padding-right: 32px;
    display: flex;
    align-items: center;
    color: rgba(255, 255, 255, 0.95);
    font-size: 16px;
    position: relative;
    cursor: pointer;

    ${({ focused }) =>
        focused &&
        `
        background-color: #666666;

        &:before {
            background-color: #1890ff; 
            content: '';
            position: absolute;
            left: 0;
            top: 0;
            bottom: 0;
            width: 7px;
        }
        `}
    ${({ isHint }) =>
        isHint &&
        `
        color: rgba(255, 255, 255, 0.7) !important;  
        cursor: default !important;
        
`};
    &:hover {
        background-color: rgba(0, 0, 0, 0.35);

        &:before {
            background-color: #1890ff;
            content: '';
            position: absolute;
            left: 0;
            top: 0;
            bottom: 0;
            width: 7px;
        }
    }
`

const IconContainer = styled.span`
    margin-right: 8px;
`

interface CommandResultProps {
    command: Command
    result: CommandResultType
    setIsPaletteShown: (newState: boolean) => void
    focused?: boolean
    isHint?: boolean
}

export function CommandResult({ result, focused, isHint, setIsPaletteShown }: CommandResultProps): JSX.Element {
    const { push } = useActions(router)

    const execute = useCallback(() => {
        result.executor({ push, ...result.utils })
        setIsPaletteShown(false)
    }, [push])

    return (
        <ResultContainer focused={focused} isHint={isHint} onClick={execute}>
            <IconContainer>
                <result.icon />
            </IconContainer>
            {result.text}
        </ResultContainer>
    )
}

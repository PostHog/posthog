import React from 'react'
import styled from 'styled-components'
import { CommandExecutor, CommandResult as CommandResultType } from './commandLogic'
import { useEventListener } from 'lib/hooks/useEventListener'
import { useCallback } from 'react'

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
    result: CommandResultType
    handleSelection: (result: CommandResultType) => void
    focused?: boolean
    isHint?: boolean
    onMouseOver?: (e: MouseEvent) => void
    onMouseOut?: (e: MouseEvent) => void
}

export function CommandResult({
    result,
    focused,
    isHint,
    handleSelection,
    onMouseOver,
    onMouseOut,
}: CommandResultProps): JSX.Element {
    const _handleKeyDown = useCallback(
        (e: KeyboardEvent) => {
            if (e.key === 'Enter' && focused) {
                handleSelection(result)
            }
        },
        [focused]
    )

    useEventListener('keydown', _handleKeyDown)

    return (
        <ResultContainer
            onMouseOver={onMouseOver}
            onMouseOut={onMouseOut}
            focused={focused}
            isHint={isHint}
            onClick={() => {
                handleSelection(result)
            }}
        >
            <IconContainer>
                <result.icon />
            </IconContainer>
            {result.display}
        </ResultContainer>
    )
}

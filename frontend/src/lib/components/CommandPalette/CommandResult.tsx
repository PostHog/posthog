import React from 'react'
import styled from 'styled-components'
import { CommandExecutor, CommandResult as CommandResultType } from './commandLogic'

interface ContainerProps {
    focused?: boolean
    isHint?: boolean
    onClick?: CommandExecutor
}

const ResultDiv = styled.div<ContainerProps>`
    height: 4rem;
    width: 100%;
    padding: 0 2rem;
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
    }
`

const IconContainer = styled.span`
    margin-right: 1rem;
`

interface CommandResultProps {
    result: CommandResultType
    handleSelection: (result: CommandResultType) => void
    focused?: boolean
    isHint?: boolean
    onMouseOver?: (e: MouseEvent) => void
}

export function CommandResult({
    result,
    focused,
    isHint,
    handleSelection,
    onMouseOver,
}: CommandResultProps): JSX.Element {
    return (
        <ResultDiv
            onMouseOver={onMouseOver}
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
        </ResultDiv>
    )
}

import React from 'react'
import styled from 'styled-components'

interface Props {
    focused?: boolean
    isHint?: boolean
}

const ResultContainer = styled.div<Props>`
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
            background-color: #FEB641; 
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
`}
`

const IconContainer = styled.span`
    margin-right: 8px;
`

interface CommandResultProps {
    Icon: any
    text: string
    focused?: boolean
    isHint?: boolean
}

export function CommandResult({ Icon, text, focused, isHint }: CommandResultProps): JSX.Element {
    return (
        <ResultContainer focused={focused} isHint={isHint}>
            <IconContainer>
                <Icon />
            </IconContainer>{' '}
            {text}
        </ResultContainer>
    )
}

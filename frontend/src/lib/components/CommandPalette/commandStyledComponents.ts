import styled from 'styled-components'
import { CommandExecutor } from './commandLogic'

export const CustomCommandBox = styled.div`
    position: fixed;
    top: 30%;
    display: flex;
    flex-direction: column;
    z-index: 9999;
    width: 36rem;
    max-height: 60%;
    overflow: hidden;
`
export const CommandTitle = styled.div`
    font-weight: bold;
    font-size: 14px;
    color: #ffffff;
    padding-top: 16px;
    padding-left: 32px;
`

export const CommandInputContainer = styled.div`
    display: flex;
    align-items: center;
    height: 4rem;
    padding: 0 1.875rem;
    border: none;
    outline: none;
    background: transparent;
    color: #fff;
    font-size: 1rem;
    line-height: 4rem;
    overflow-y: scroll;
`

export const CommandInputElement = styled.input`
    flex-grow: 1;
    height: 4rem;
    padding-left: 1.875rem;
    border: none;
    outline: none;
    background: transparent;
    color: #fff;
    font-size: 1rem;
    line-height: 4rem;
    overflow-y: scroll;
`

interface ResultBoxProps {
    focused?: boolean
    isHint?: boolean
    onClick?: CommandExecutor
}

export const ResultBox = styled.div<ResultBoxProps>`
    height: 4rem;
    width: 100%;
    padding: 0 1.875rem;
    display: flex;
    align-items: center;
    color: rgba(255, 255, 255, 0.95);
    font-size: 1rem;
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
            width: 0.375rem;
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

export const Scope = styled.div`
    height: 1.5rem;
    line-height: 1.5rem;
    width: 100%;
    padding: 0 1.875rem;
    background-color: rgba(255, 255, 255, 0.1);
    color: rgba(255, 255, 255, 0.8);
    font-size: 0.75rem;
    text-transform: uppercase;
    font-weight: bold;
`

export const ResultsContainer = styled.div`
    overflow-y: scroll;
`

export const ResultIconContainer = styled.span`
    display: flex;
    align-items: center;
    width: 1rem;
    height: 100%;
`

export const ResultDisplay = styled.span`
    padding-left: 1.5rem;
`

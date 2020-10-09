import styled from 'styled-components'

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
    padding: 0 2rem;
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
    padding-left: 1rem;
    border: none;
    outline: none;
    background: transparent;
    color: #fff;
    font-size: 1rem;
    line-height: 4rem;
    overflow-y: scroll;
`

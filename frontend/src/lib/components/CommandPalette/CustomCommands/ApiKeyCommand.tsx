import React from 'react'
import { useActions, useValues } from 'kea'
import { apiKeyCommandLogic } from './apiKeyCommandLogic'
import { CustomCommandBox, CommandTitle, CommandInputContainer, CommandInputElement } from '../commandStyledComponents'
import { personalAPIKeysLogic } from 'lib/components/PersonalAPIKeys/personalAPIKeysLogic'
import styled from 'styled-components'

const SuccessContainer = styled.div`
    padding: 32px;
    color: rgba(255, 255, 255, 0.9);
`

const KeyContainer = styled.div`
    background-color: #666666;
    font-family: 'IBM Plex Mono', 'Courier New', Courier, monospace;
    text-align: center;
    border-radius: 2px;
    padding: 8px;
    margin: 16px 0;
`

const HighlightNotice = styled.div`
    color: #ec6f48;
`

interface ApiKeyCommandProps {
    handleCancel: () => void
}

export function ApiKeyCommand({ handleCancel }: ApiKeyCommandProps): JSX.Element {
    const { setLabelInput } = useActions(apiKeyCommandLogic)
    const { labelInput } = useValues(apiKeyCommandLogic)
    const { createKey } = useActions(personalAPIKeysLogic)
    const { latestKey } = useValues(personalAPIKeysLogic)

    const handleKeyDown = (event: KeyboardEvent): void => {
        if (event.key === 'Escape') {
            handleCancel()
        } else if (event.key === 'Enter' && labelInput !== '') {
            createKey(labelInput)
        }
    }

    return (
        <CustomCommandBox className="card bg-dark">
            <CommandTitle>Create personal API key</CommandTitle>
            {!latestKey && (
                <CommandInputContainer>
                    <CommandInputElement
                        autoFocus
                        value={labelInput}
                        onKeyDown={handleKeyDown}
                        onChange={(event) => {
                            setLabelInput(event.target.value)
                        }}
                        placeholder="enter a label for your key (e.g. Zapier)"
                    />
                </CommandInputContainer>
            )}
            {latestKey && (
                <SuccessContainer>
                    <div>Your personal API key is ready and has been copied to your clipboard!</div>
                    <KeyContainer>{latestKey.value}</KeyContainer>
                    <HighlightNotice>
                        Remember to copy your key before closing this window, your key cannot be shown again.
                    </HighlightNotice>
                </SuccessContainer>
            )}
        </CustomCommandBox>
    )
}

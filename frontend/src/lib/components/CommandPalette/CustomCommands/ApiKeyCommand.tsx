import React from 'react'
import { useActions, useValues } from 'kea'
import { apiKeyCommandLogic } from './apiKeyCommandLogic'
import { personalAPIKeysLogic } from 'lib/components/PersonalAPIKeys/personalAPIKeysLogic'
import { EditOutlined } from '@ant-design/icons'

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
        <div className="card bg-dark">
            {!latestKey && (
                <div>
                    <EditOutlined />
                    <input
                        autoFocus
                        value={labelInput}
                        onKeyDown={handleKeyDown}
                        onChange={(event) => {
                            setLabelInput(event.target.value)
                        }}
                        placeholder="enter a label for your key (e.g. Zapier)"
                    />
                </div>
            )}
            {latestKey && (
                <div>
                    <div>Your personal API key is ready and has been copied to your clipboard!</div>
                    <div>{latestKey.value}</div>
                    <div>Remember to copy your key before closing this window, your key cannot be shown again.</div>
                </div>
            )}
            <div>Creating a Personal API Key</div>
        </div>
    )
}

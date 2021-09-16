import React, { useState } from 'react'
import { Button } from '@storybook/components'
import { ApiHistory } from './ApiHistory'

export const ApiForm = ({ saveApi, selectedConnection }) => {
    const [apiHost, setApiHost] = useState(selectedConnection.apiHost)
    const [apiKey, setApiKey] = useState(selectedConnection.apiKey)

    return (
        <div>
            <div style={{ margin: 10 }}>
                API Host:
                <br />
                <input value={apiHost} onChange={(e) => setApiHost(e.target.value)} style={{ width: '100%' }} />
            </div>
            <div style={{ margin: 10 }}>
                API Key:
                <br />
                <input value={apiKey} onChange={(e) => setApiKey(e.target.value)} style={{ width: '100%' }} />
            </div>
            <div style={{ margin: 10 }}>
                <Button primary onClick={() => saveApi(apiHost, apiKey)}>
                    Save
                </Button>
            </div>
            <ApiHistory saveApi={saveApi} />
        </div>
    )
}

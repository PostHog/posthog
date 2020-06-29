import React from 'react'
import Snippet from './snippet'

function APISnippet({ user }) {
    let url = window.location.origin
    return (
        <Snippet>
            <span>
                {'POST ' +
                    url +
                    '/capture/\nContent-Type: application/json\nBody:\n{\n\t"api_key": "' +
                    user.team.api_token +
                    '",\n\t"event": "[event name]",\n\t"properties": {\n\t\t"distinct_id": "[your users\' distinct id]",\n\t\t"key1": "value1",\n\t\t"key2": "value2",\n\t},\n\t"timestamp": "[optional timestamp in ISO 8601 format]"\n}'}
            </span>
        </Snippet>
    )
}

export function APIInstructions({ user }) {
    return (
        <>
            <h3>Usage</h3>
            <APISnippet user={user}></APISnippet>
        </>
    )
}

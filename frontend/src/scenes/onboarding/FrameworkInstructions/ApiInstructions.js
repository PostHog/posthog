import React from 'react'
import { CodeSnippet } from './CodeSnippet'

function APISnippet({ user }) {
    let url = window.location.origin
    return (
        <CodeSnippet language="http">
            {'POST ' +
                url +
                '/capture/\nContent-Type: application/json\n\n{\n\t"api_key": "' +
                user.team.api_token +
                '",\n\t"event": "[event name]",\n\t"properties": {\n\t\t"distinct_id": "[your users\' distinct id]",\n\t\t"key1": "value1",\n\t\t"key2": "value2",\n\t},\n\t"timestamp": "[optional timestamp in ISO 8601 format]"\n}'}
        </CodeSnippet>
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

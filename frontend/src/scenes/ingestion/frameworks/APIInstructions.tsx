import React from 'react'
import { CodeSnippet, Language } from './CodeSnippet'
import { useValues } from 'kea'
import { userLogic } from 'scenes/userLogic'

function APISnippet(): JSX.Element {
    const { user } = useValues(userLogic)
    const url = window.location.origin
    return (
        <CodeSnippet language={Language.HTTP}>
            {'POST ' +
                url +
                '/capture/\nContent-Type: application/json\n\n{\n\t"api_key": "' +
                user?.team?.api_token +
                '",\n\t"event": "[event name]",\n\t"properties": {\n\t\t"distinct_id": "[your users\' distinct id]",\n\t\t"key1": "value1",\n\t\t"key2": "value2",\n\t},\n\t"timestamp": "[optional timestamp in ISO 8601 format]"\n}'}
        </CodeSnippet>
    )
}

export function APIInstructions(): JSX.Element {
    return (
        <>
            <h3>Usage</h3>
            <APISnippet />
        </>
    )
}

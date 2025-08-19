import { useValues } from 'kea'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { apiHostOrigin } from 'lib/utils/apiHost'
import { teamLogic } from 'scenes/teamLogic'

import { PersonModeEventPropertyInstructions } from '../shared-snippets'

function APISnippet(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const url = apiHostOrigin()

    return (
        <CodeSnippet language={Language.HTTP}>
            {'POST ' +
                url +
                '/capture/\nContent-Type: application/json\n\n{\n\t"api_key": "' +
                currentTeam?.api_token +
                '",\n\t"event": "[event name]",\n\t"properties": {\n\t\t"distinct_id": "[your users\' distinct id]",\n\t\t"key1": "value1",\n\t\t"key2": "value2"\n\t},\n\t"timestamp": "[optional timestamp in ISO 8601 format]"\n}'}
        </CodeSnippet>
    )
}

export function ProductAnalyticsAPIInstructions(): JSX.Element {
    return (
        <>
            <h3>Usage</h3>
            <APISnippet />
            <PersonModeEventPropertyInstructions />
        </>
    )
}

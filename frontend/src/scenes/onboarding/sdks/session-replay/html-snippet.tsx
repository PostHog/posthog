import { LemonDivider } from 'lib/lemon-ui/LemonDivider'

import { SDKHtmlSnippetInstructions } from '../sdk-install-instructions/html-snippet'
import { SessionReplayFinalSteps } from '../shared-snippets'

export function HTMLSnippetInstructions(): JSX.Element {
    return (
        <>
            <SDKHtmlSnippetInstructions />
            <LemonDivider thick dashed className="my-4" />
            <h3>Final steps</h3>
            <SessionReplayFinalSteps />
        </>
    )
}

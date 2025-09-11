import { SDKHtmlSnippetInstructions } from '../sdk-install-instructions/html-snippet'
import { SessionReplayFinalSteps } from '../shared-snippets'

export function HTMLSnippetInstructions(): JSX.Element {
    return (
        <>
            <SDKHtmlSnippetInstructions />
            <SessionReplayFinalSteps />
        </>
    )
}

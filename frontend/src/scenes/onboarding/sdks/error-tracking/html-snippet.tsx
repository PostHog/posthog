import { SDKHtmlSnippetInstructions } from '../sdk-install-instructions/html-snippet'
import { ErrorTrackingAllJSFinalSteps } from './FinalSteps'

export function HTMLSnippetInstructions(): JSX.Element {
    return (
        <>
            <SDKHtmlSnippetInstructions />
            <ErrorTrackingAllJSFinalSteps />
        </>
    )
}

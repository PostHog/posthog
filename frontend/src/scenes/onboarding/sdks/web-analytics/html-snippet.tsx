import { SDKHtmlSnippetInstructions } from '../sdk-install-instructions/html-snippet'
import { WebAnalyticsAllJSFinalSteps } from './FinalSteps'

export function HTMLSnippetInstructions(): JSX.Element {
    return (
        <>
            <SDKHtmlSnippetInstructions />
            <WebAnalyticsAllJSFinalSteps />
        </>
    )
}

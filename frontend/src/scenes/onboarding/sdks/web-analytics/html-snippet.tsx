import { WebAnalyticsAllJSFinalSteps } from 'scenes/onboarding/sdks/web-analytics/AllJSFinalSteps'

import { SDKHtmlSnippetInstructions } from '../sdk-install-instructions/html-snippet'

export function HTMLSnippetInstructions(): JSX.Element {
    return (
        <>
            <SDKHtmlSnippetInstructions />
            <WebAnalyticsAllJSFinalSteps />
        </>
    )
}

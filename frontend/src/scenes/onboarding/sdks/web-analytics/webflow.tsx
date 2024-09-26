import { WebAnalyticsAllJSFinalSteps } from 'scenes/onboarding/sdks/web-analytics/AllJSFinalSteps'

import { SDKInstallWebflowInstructions } from '../sdk-install-instructions'

export function WebflowInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallWebflowInstructions />
            <WebAnalyticsAllJSFinalSteps />
        </>
    )
}

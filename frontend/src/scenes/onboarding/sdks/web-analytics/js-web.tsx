import { WebAnalyticsAllJSFinalSteps } from 'scenes/onboarding/sdks/web-analytics/AllJSFinalSteps'

import { SDKInstallJSWebInstructions } from '../sdk-install-instructions'

export function JSWebInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallJSWebInstructions />
            <WebAnalyticsAllJSFinalSteps />
        </>
    )
}

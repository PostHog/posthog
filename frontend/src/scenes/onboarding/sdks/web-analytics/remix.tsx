import { WebAnalyticsAllJSFinalSteps } from 'scenes/onboarding/sdks/web-analytics/AllJSFinalSteps'

import { SDKInstallRemixJSInstructions } from '../sdk-install-instructions/remix'

export function RemixInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallRemixJSInstructions />
            <WebAnalyticsAllJSFinalSteps />
        </>
    )
}

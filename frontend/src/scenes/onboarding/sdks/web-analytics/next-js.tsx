import { WebAnalyticsAllJSFinalSteps } from 'scenes/onboarding/sdks/web-analytics/AllJSFinalSteps'

import { SDKInstallNextJSInstructions } from '../sdk-install-instructions/next-js'

export function NextJSInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallNextJSInstructions />
            <WebAnalyticsAllJSFinalSteps />
        </>
    )
}

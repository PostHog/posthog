import { WebAnalyticsAllJSFinalSteps } from 'scenes/onboarding/sdks/web-analytics/AllJSFinalSteps'

import { SDKInstallReactInstructions } from '../sdk-install-instructions/react'

export function ReactInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallReactInstructions />
            <WebAnalyticsAllJSFinalSteps />
        </>
    )
}

import { WebAnalyticsAllJSFinalSteps } from 'scenes/onboarding/sdks/web-analytics/AllJSFinalSteps'

import { SDKInstallFramerInstructions } from '../sdk-install-instructions'

export function FramerInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallFramerInstructions />
            <WebAnalyticsAllJSFinalSteps />
        </>
    )
}

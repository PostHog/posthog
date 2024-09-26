import { WebAnalyticsAllJSFinalSteps } from 'scenes/onboarding/sdks/web-analytics/AllJSFinalSteps'

import { SDKInstallBubbleInstructions } from '../sdk-install-instructions'

export function BubbleInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallBubbleInstructions />
            <WebAnalyticsAllJSFinalSteps />
        </>
    )
}

import { WebAnalyticsAllJSFinalSteps } from 'scenes/onboarding/sdks/web-analytics/AllJSFinalSteps'

import { SDKInstallVueInstructions } from '../sdk-install-instructions'

export function VueInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallVueInstructions />
            <WebAnalyticsAllJSFinalSteps />
        </>
    )
}

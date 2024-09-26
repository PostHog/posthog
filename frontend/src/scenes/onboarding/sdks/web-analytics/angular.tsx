import { WebAnalyticsAllJSFinalSteps } from 'scenes/onboarding/sdks/web-analytics/AllJSFinalSteps'

import { SDKInstallAngularInstructions } from '../sdk-install-instructions'

export function AngularInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallAngularInstructions />
            <WebAnalyticsAllJSFinalSteps />
        </>
    )
}

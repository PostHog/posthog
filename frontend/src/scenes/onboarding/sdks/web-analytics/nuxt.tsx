import { WebAnalyticsAllJSFinalSteps } from 'scenes/onboarding/sdks/web-analytics/AllJSFinalSteps'

import { SDKInstallNuxtJSInstructions } from '../sdk-install-instructions/nuxt'

export function NuxtJSInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallNuxtJSInstructions />
            <WebAnalyticsAllJSFinalSteps />
        </>
    )
}

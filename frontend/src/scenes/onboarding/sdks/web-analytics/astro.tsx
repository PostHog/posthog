import { WebAnalyticsAllJSFinalSteps } from 'scenes/onboarding/sdks/web-analytics/AllJSFinalSteps'

import { SDKInstallAstroInstructions } from '../sdk-install-instructions'

export function AstroInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallAstroInstructions />
            <WebAnalyticsAllJSFinalSteps />
        </>
    )
}

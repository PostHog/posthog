import { WebAnalyticsMobileFinalSteps } from 'scenes/onboarding/sdks/web-analytics/FinalSteps'

import { SDKInstallIOSInstructions, SDKInstallIOSTrackScreenInstructions } from '../sdk-install-instructions'

export function iOSInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallIOSInstructions includeReplay={false} />
            <WebAnalyticsMobileFinalSteps />
            <SDKInstallIOSTrackScreenInstructions />
        </>
    )
}

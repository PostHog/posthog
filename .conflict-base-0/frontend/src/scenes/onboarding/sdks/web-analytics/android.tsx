import { WebAnalyticsMobileFinalSteps } from 'scenes/onboarding/sdks/web-analytics/FinalSteps'

import { SDKInstallAndroidInstructions, SDKInstallAndroidTrackScreenInstructions } from '../sdk-install-instructions'

export function AndroidInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallAndroidInstructions includeReplay={false} />
            <WebAnalyticsMobileFinalSteps />
            <SDKInstallAndroidTrackScreenInstructions />
        </>
    )
}

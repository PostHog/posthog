import { WebAnalyticsMobileFinalSteps } from 'scenes/onboarding/sdks/web-analytics/FinalSteps'

import { SDKInstallFlutterInstructions, SDKInstallFlutterTrackScreenInstructions } from '../sdk-install-instructions'

export function FlutterInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallFlutterInstructions includeReplay={false} />
            <WebAnalyticsMobileFinalSteps />
            <SDKInstallFlutterTrackScreenInstructions />
        </>
    )
}

import { SDKInstallFramerInstructions } from '../sdk-install-instructions'
import { WebAnalyticsAllJSFinalSteps } from './FinalSteps'

export function FramerInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallFramerInstructions />
            <WebAnalyticsAllJSFinalSteps />
        </>
    )
}

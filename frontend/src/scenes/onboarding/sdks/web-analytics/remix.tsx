import { SDKInstallRemixJSInstructions } from '../sdk-install-instructions/remix'
import { WebAnalyticsAllJSFinalSteps } from './FinalSteps'

export function RemixInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallRemixJSInstructions />
            <WebAnalyticsAllJSFinalSteps />
        </>
    )
}

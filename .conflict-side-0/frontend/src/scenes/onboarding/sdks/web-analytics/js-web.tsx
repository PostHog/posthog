import { SDKInstallJSWebInstructions } from '../sdk-install-instructions'
import { WebAnalyticsAllJSFinalSteps } from './FinalSteps'

export function JSWebInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallJSWebInstructions />
            <WebAnalyticsAllJSFinalSteps />
        </>
    )
}

import { SDKInstallJSWebInstructions } from '../sdk-install-instructions'
import { ErrorTrackingAllJSFinalSteps } from './FinalSteps'

export function JSWebInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallJSWebInstructions />
            <ErrorTrackingAllJSFinalSteps />
        </>
    )
}

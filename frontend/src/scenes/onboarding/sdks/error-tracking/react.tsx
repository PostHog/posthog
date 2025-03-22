import { SDKInstallReactInstructions } from '../sdk-install-instructions/react'
import { ErrorTrackingAllJSFinalSteps } from './FinalSteps'

export function ReactInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallReactInstructions />
            <ErrorTrackingAllJSFinalSteps />
        </>
    )
}

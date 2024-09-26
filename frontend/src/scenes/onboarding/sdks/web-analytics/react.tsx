import { SDKInstallReactInstructions } from '../sdk-install-instructions/react'
import { WebAnalyticsAllJSFinalSteps } from './FinalSteps'

export function ReactInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallReactInstructions />
            <WebAnalyticsAllJSFinalSteps />
        </>
    )
}

import { SDKInstallWebflowInstructions } from '../sdk-install-instructions'
import { WebAnalyticsAllJSFinalSteps } from './FinalSteps'

export function WebflowInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallWebflowInstructions />
            <WebAnalyticsAllJSFinalSteps />
        </>
    )
}

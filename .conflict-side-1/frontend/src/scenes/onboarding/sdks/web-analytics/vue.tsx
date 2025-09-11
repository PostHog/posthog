import { SDKInstallVueInstructions } from '../sdk-install-instructions'
import { WebAnalyticsAllJSFinalSteps } from './FinalSteps'

export function VueInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallVueInstructions />
            <WebAnalyticsAllJSFinalSteps />
        </>
    )
}

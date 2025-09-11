import { SDKInstallNextJSInstructions } from '../sdk-install-instructions/next-js'
import { WebAnalyticsAllJSFinalSteps } from './FinalSteps'

export function NextJSInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallNextJSInstructions />
            <WebAnalyticsAllJSFinalSteps />
        </>
    )
}

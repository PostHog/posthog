import { SDKInstallAngularInstructions } from '../sdk-install-instructions'
import { WebAnalyticsAllJSFinalSteps } from './FinalSteps'

export function AngularInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallAngularInstructions />
            <WebAnalyticsAllJSFinalSteps />
        </>
    )
}

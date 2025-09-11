import { SDKInstallNuxtJSInstructions } from '../sdk-install-instructions/nuxt'
import { WebAnalyticsAllJSFinalSteps } from './FinalSteps'

export function NuxtJSInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallNuxtJSInstructions />
            <WebAnalyticsAllJSFinalSteps />
        </>
    )
}

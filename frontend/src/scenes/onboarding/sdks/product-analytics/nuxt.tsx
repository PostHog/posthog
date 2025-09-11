import { SDKInstallNuxtJSInstructions } from '../sdk-install-instructions/nuxt'
import { ProductAnalyticsAllJSFinalSteps } from './AllJSFinalSteps'

export function ProductAnalyticsNuxtJSInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallNuxtJSInstructions />
            <ProductAnalyticsAllJSFinalSteps />
        </>
    )
}

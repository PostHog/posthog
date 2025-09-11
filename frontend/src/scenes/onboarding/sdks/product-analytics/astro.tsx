import { SDKInstallAstroInstructions } from '../sdk-install-instructions/astro'
import { ProductAnalyticsAllJSFinalSteps } from './AllJSFinalSteps'

export function ProductAnalyticsAstroInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallAstroInstructions />
            <ProductAnalyticsAllJSFinalSteps />
        </>
    )
}

import { SDKInstallRemixJSInstructions } from '../sdk-install-instructions/remix'
import { ProductAnalyticsAllJSFinalSteps } from './AllJSFinalSteps'

export function ProductAnalyticsRemixJSInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallRemixJSInstructions />
            <ProductAnalyticsAllJSFinalSteps />
        </>
    )
}

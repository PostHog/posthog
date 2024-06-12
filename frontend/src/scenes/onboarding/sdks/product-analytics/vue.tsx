import { SDKInstallVueInstructions } from '../sdk-install-instructions/vue'
import { ProductAnalyticsAllJSFinalSteps } from './AllJSFinalSteps'

export function ProductAnalyticsVueInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallVueInstructions />
            <ProductAnalyticsAllJSFinalSteps />
        </>
    )
}

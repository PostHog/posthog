import { SDKInstallWebflowInstructions } from '../sdk-install-instructions/webflow'
import { ProductAnalyticsAllJSFinalSteps } from './AllJSFinalSteps'

export function ProductAnalyticsWebflowInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallWebflowInstructions />
            <ProductAnalyticsAllJSFinalSteps />
        </>
    )
}

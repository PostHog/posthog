import { SDKInstallBubbleInstructions } from '../sdk-install-instructions/bubble'
import { ProductAnalyticsAllJSFinalSteps } from './AllJSFinalSteps'

export function ProductAnalyticsBubbleInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallBubbleInstructions />
            <ProductAnalyticsAllJSFinalSteps />
        </>
    )
}

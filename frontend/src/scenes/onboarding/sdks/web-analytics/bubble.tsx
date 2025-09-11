import { SDKInstallBubbleInstructions } from '../sdk-install-instructions'
import { WebAnalyticsAllJSFinalSteps } from './FinalSteps'

export function BubbleInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallBubbleInstructions />
            <WebAnalyticsAllJSFinalSteps />
        </>
    )
}

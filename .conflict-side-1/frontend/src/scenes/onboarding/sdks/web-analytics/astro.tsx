import { SDKInstallAstroInstructions } from '../sdk-install-instructions'
import { WebAnalyticsAllJSFinalSteps } from './FinalSteps'

export function AstroInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallAstroInstructions />
            <WebAnalyticsAllJSFinalSteps />
        </>
    )
}

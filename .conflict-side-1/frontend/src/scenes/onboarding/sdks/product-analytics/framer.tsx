import { SDKInstallFramerInstructions } from '../sdk-install-instructions/framer'
import { ProductAnalyticsAllJSFinalSteps } from './AllJSFinalSteps'

export function ProductAnalyticsFramerInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallFramerInstructions />
            <ProductAnalyticsAllJSFinalSteps />
        </>
    )
}

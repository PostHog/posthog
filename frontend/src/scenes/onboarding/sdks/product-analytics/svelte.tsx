import { SDKInstallSvelteJSInstructions } from '../sdk-install-instructions/svelte'
import { ProductAnalyticsAllJSFinalSteps } from './AllJSFinalSteps'

export function ProductAnalyticsSvelteJSInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallSvelteJSInstructions />
            <ProductAnalyticsAllJSFinalSteps />
        </>
    )
}

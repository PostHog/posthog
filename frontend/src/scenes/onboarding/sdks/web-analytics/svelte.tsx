import { SDKInstallSvelteJSInstructions } from '../sdk-install-instructions/svelte'
import { WebAnalyticsAllJSFinalSteps } from './FinalSteps'

export function SvelteInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallSvelteJSInstructions />
            <WebAnalyticsAllJSFinalSteps />
        </>
    )
}

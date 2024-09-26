import { WebAnalyticsAllJSFinalSteps } from 'scenes/onboarding/sdks/web-analytics/AllJSFinalSteps'

import { SDKInstallSvelteJSInstructions } from '../sdk-install-instructions/svelte'

export function SvelteInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallSvelteJSInstructions />
            <WebAnalyticsAllJSFinalSteps />
        </>
    )
}

import { LemonDivider } from '@posthog/lemon-ui'

import { SDKInstallNuxtJSInstructions } from '../sdk-install-instructions/nuxt'
import { ProductAnalyticsAllJSFinalSteps } from './AllJSFinalSteps'

export function ProductAnalyticsNuxtJSInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallNuxtJSInstructions />
            <LemonDivider thick dashed className="my-4" />
            <ProductAnalyticsAllJSFinalSteps />
        </>
    )
}

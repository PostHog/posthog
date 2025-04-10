import { LemonDivider } from '@posthog/lemon-ui'

import { SDKInstallReactInstructions } from '../sdk-install-instructions/react'
import { ProductAnalyticsAllJSFinalSteps } from './AllJSFinalSteps'

export function ProductAnalyticsReactInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallReactInstructions />
            <LemonDivider thick dashed className="my-4" />
            <ProductAnalyticsAllJSFinalSteps />
        </>
    )
}

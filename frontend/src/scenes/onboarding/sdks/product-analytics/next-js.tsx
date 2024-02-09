import { LemonDivider } from '@posthog/lemon-ui'

import { SDKInstallNextJSInstructions } from '../sdk-install-instructions/next-js'
import { ProductAnaltyicsAllJSFinalSteps } from './AllJSFinalSteps'

export function ProductAnalyticsNextJSInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallNextJSInstructions />
            <LemonDivider thick dashed className="my-4" />
            <ProductAnaltyicsAllJSFinalSteps />
        </>
    )
}

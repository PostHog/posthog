import { LemonDivider } from '@posthog/lemon-ui'

import { SDKInstallJSWebInstructions } from '../sdk-install-instructions'
import { ProductAnaltyicsAllJSFinalSteps } from './AllJSFinalSteps'

export function JSWebInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallJSWebInstructions />
            <LemonDivider thick dashed className="my-4" />
            <ProductAnaltyicsAllJSFinalSteps />
        </>
    )
}

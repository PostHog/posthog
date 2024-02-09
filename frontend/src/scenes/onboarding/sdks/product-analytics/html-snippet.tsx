import { LemonDivider } from '@posthog/lemon-ui'

import { SDKHtmlSnippetInstructions } from '../sdk-install-instructions/html-snippet'
import { ProductAnaltyicsAllJSFinalSteps } from './AllJSFinalSteps'

export function HTMLSnippetInstructions(): JSX.Element {
    return (
        <>
            <SDKHtmlSnippetInstructions />
            <LemonDivider thick dashed className="my-4" />
            <ProductAnaltyicsAllJSFinalSteps />
        </>
    )
}

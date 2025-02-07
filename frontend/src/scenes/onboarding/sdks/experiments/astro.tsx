import { LemonDivider } from '@posthog/lemon-ui/LemonDivider'

import { SDKKey } from '~/types'

import { SDKInstallAstroInstructions } from '../sdk-install-instructions'
import { ExperimentsImplementationSnippet } from './ExperimentsImplementationSnippet'

export function ExperimentsAstroInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallAstroInstructions />
            <LemonDivider thick dashed className="my-4" />
            <ExperimentsImplementationSnippet sdkKey={SDKKey.JS_WEB} />
        </>
    )
}

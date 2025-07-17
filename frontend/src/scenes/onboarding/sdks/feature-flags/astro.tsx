import { SDKKey } from '~/types'

import { SDKInstallAstroInstructions } from '../sdk-install-instructions/astro'
import { FlagImplementationSnippet } from './flagImplementationSnippet'

export function FeatureFlagsAstroInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallAstroInstructions hideWizard />
            <FlagImplementationSnippet sdkKey={SDKKey.JS_WEB} />
        </>
    )
}

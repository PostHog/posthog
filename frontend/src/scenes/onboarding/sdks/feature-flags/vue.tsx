import { SDKKey } from '~/types'

import { SDKInstallVueInstructions } from '../sdk-install-instructions/vue'
import { FlagImplementationSnippet } from './flagImplementationSnippet'

export function FeatureFlagsVueInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallVueInstructions />
            <FlagImplementationSnippet sdkKey={SDKKey.JS_WEB} />
        </>
    )
}

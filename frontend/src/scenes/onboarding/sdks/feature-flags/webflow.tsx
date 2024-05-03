import { SDKKey } from '~/types'

import { SDKInstallWebflowInstructions } from '../sdk-install-instructions/webflow'
import { FlagImplementationSnippet } from './flagImplementationSnippet'

export function FeatureFlagsWebflowInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallWebflowInstructions />
            <FlagImplementationSnippet sdkKey={SDKKey.JS_WEB} />
        </>
    )
}

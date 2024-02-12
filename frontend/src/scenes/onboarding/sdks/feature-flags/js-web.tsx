import { LemonDivider } from 'lib/lemon-ui/LemonDivider'

import { SDKKey } from '~/types'

import { SDKInstallJSWebInstructions } from '../sdk-install-instructions'
import { FlagImplementationSnippet } from './flagImplementationSnippet'

export function FeatureFlagsJSWebInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallJSWebInstructions />
            <LemonDivider thick dashed className="my-4" />
            <FlagImplementationSnippet sdkKey={SDKKey.JS_WEB} />
        </>
    )
}

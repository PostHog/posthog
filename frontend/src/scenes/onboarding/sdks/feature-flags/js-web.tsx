import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { FlagImplementationSnippet } from './flagImplementationSnippet'
import { SDKKey } from '~/types'
import { SDKInstallJSWebInstructions } from '../sdk-install-instructions'

export function FeatureFlagsJSWebInstructions(): React.ReactNode {
    return (
        <>
            <SDKInstallJSWebInstructions />
            <LemonDivider thick dashed className="my-4" />
            <FlagImplementationSnippet sdkKey={SDKKey.JS_WEB} />
        </>
    )
}

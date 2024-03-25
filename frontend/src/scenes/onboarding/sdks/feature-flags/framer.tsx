import { SDKKey } from '~/types'

import { SDKInstallFramerInstructions } from '../sdk-install-instructions/framer'
import { FlagImplementationSnippet } from './flagImplementationSnippet'

export function FeatureFlagsFramerInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallFramerInstructions />
            <FlagImplementationSnippet sdkKey={SDKKey.JS_WEB} />
        </>
    )
}

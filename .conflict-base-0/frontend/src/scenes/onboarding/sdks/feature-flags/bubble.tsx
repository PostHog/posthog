import { SDKKey } from '~/types'

import { SDKInstallBubbleInstructions } from '../sdk-install-instructions/bubble'
import { FlagImplementationSnippet } from './flagImplementationSnippet'

export function FeatureFlagsBubbleInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallBubbleInstructions />
            <FlagImplementationSnippet sdkKey={SDKKey.JS_WEB} />
        </>
    )
}

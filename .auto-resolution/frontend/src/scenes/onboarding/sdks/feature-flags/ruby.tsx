import { SDKKey } from '~/types'

import { SDKInstallRubyInstructions } from '../sdk-install-instructions'
import { FlagImplementationSnippet } from './flagImplementationSnippet'

export function FeatureFlagsRubyInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallRubyInstructions />
            <FlagImplementationSnippet sdkKey={SDKKey.RUBY} />
        </>
    )
}

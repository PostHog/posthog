import { FlagImplementationSnippet } from './flagImplementationSnippet'
import { SDKKey } from '~/types'
import { SDKInstallRubyInstructions } from '../sdk-install-instructions'

export function FeatureFlagsRubyInstructions(): React.ReactNode {
    return (
        <>
            <SDKInstallRubyInstructions />
            <FlagImplementationSnippet sdkKey={SDKKey.RUBY} />
        </>
    )
}

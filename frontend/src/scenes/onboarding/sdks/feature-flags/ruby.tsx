import { FlagImplementationSnippet } from './flagImplementationSnippet'
import { SDKKey } from '~/types'
import { SDKInstallRubyInstructions } from '../sdk-install-instructions'

export function FeatureFlagsRubyInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallRubyInstructions />
            <FlagImplementationSnippet sdkKey={SDKKey.RUBY} />
        </>
    )
}

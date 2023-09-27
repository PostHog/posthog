import { SDKKey } from '~/types'
import { FlagImplementationSnippet } from './flagImplementationSnippet'
import { SDKInstallGoInstructions } from '../sdk-install-instructions'

export function FeatureFlagsGoInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallGoInstructions />
            <FlagImplementationSnippet sdkKey={SDKKey.GO} />
        </>
    )
}

import { SDKKey } from '~/types'
import { FlagImplementationSnippet } from './flagImplementationSnippet'
import { SDKInstallGoInstructions } from '../sdk-install-instructions'

export function FeatureFlagsGoInstructions(): React.ReactNode {
    return (
        <>
            <SDKInstallGoInstructions />
            <FlagImplementationSnippet sdkKey={SDKKey.GO} />
        </>
    )
}

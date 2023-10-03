import { FlagImplementationSnippet } from './flagImplementationSnippet'
import { SDKKey } from '~/types'
import { SDKInstallNodeInstructions } from '../sdk-install-instructions'

export function FeatureFlagsNodeInstructions(): React.ReactNode {
    return (
        <>
            <SDKInstallNodeInstructions />
            <FlagImplementationSnippet sdkKey={SDKKey.NODE_JS} />
        </>
    )
}

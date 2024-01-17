import { SDKKey } from '~/types'

import { SDKInstallNodeInstructions } from '../sdk-install-instructions'
import { FlagImplementationSnippet } from './flagImplementationSnippet'

export function FeatureFlagsNodeInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallNodeInstructions />
            <FlagImplementationSnippet sdkKey={SDKKey.NODE_JS} />
        </>
    )
}

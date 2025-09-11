import { SDKKey } from '~/types'

import { SDKInstallGoInstructions } from '../sdk-install-instructions'
import { FlagImplementationSnippet } from './flagImplementationSnippet'

export function FeatureFlagsGoInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallGoInstructions />
            <FlagImplementationSnippet sdkKey={SDKKey.GO} />
        </>
    )
}

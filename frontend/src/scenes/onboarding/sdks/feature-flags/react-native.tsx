import { SDKKey } from '~/types'

import { SDKInstallRNInstructions } from '../sdk-install-instructions'
import { FlagImplementationSnippet } from './flagImplementationSnippet'

export function FeatureFlagsRNInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallRNInstructions />
            <FlagImplementationSnippet sdkKey={SDKKey.REACT_NATIVE} />
        </>
    )
}

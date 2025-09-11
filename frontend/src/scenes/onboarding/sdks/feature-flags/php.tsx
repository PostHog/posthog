import { SDKKey } from '~/types'

import { SDKInstallPHPInstructions } from '../sdk-install-instructions'
import { FlagImplementationSnippet } from './flagImplementationSnippet'

export function FeatureFlagsPHPInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallPHPInstructions />
            <FlagImplementationSnippet sdkKey={SDKKey.PHP} />
        </>
    )
}

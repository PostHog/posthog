import { SDKKey } from '~/types'

import { SDKInstallLaravelInstructions } from '../sdk-install-instructions'
import { FlagImplementationSnippet } from './flagImplementationSnippet'

export function FeatureFlagsLaravelInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallLaravelInstructions />
            <FlagImplementationSnippet sdkKey={SDKKey.PHP} />
        </>
    )
}

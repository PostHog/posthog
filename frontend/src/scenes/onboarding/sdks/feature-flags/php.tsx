import { SDKKey } from '~/types'
import { FlagImplementationSnippet } from './flagImplementationSnippet'
import { SDKInstallPHPInstructions } from '../sdk-install-instructions'

export function FeatureFlagsPHPInstructions(): React.ReactNode {
    return (
        <>
            <SDKInstallPHPInstructions />
            <FlagImplementationSnippet sdkKey={SDKKey.PHP} />
        </>
    )
}

import { SDKKey } from '~/types'
import { FlagImplementationSnippet } from './flagImplementationSnippet'
import { SDKInstallPHPInstructions } from '../sdk-install-instructions'

export function FeatureFlagsPHPInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallPHPInstructions />
            <FlagImplementationSnippet sdkKey={SDKKey.PHP} />
        </>
    )
}

import { FlagImplementationSnippet } from './flagImplementationSnippet'
import { SDKKey } from '~/types'
import { SDKInstallIOSInstructions } from '../sdk-install-instructions'

export function FeatureFlagsIOSInstructions(): React.ReactNode {
    return (
        <>
            <SDKInstallIOSInstructions />
            <FlagImplementationSnippet sdkKey={SDKKey.IOS} />
        </>
    )
}

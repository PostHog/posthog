import { FlagImplementationSnippet } from './flagImplementationSnippet'
import { SDKKey } from '~/types'
import { SDKInstallAndroidInstructions } from '../sdk-install-instructions'

export function FeatureFlagsAndroidInstructions(): React.ReactNode {
    return (
        <>
            <SDKInstallAndroidInstructions />
            <FlagImplementationSnippet sdkKey={SDKKey.ANDROID} />
        </>
    )
}

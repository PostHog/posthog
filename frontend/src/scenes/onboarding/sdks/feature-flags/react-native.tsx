import { SDKInstallRNInstructions } from '../sdk-install-instructions'
import { FlagImplementationSnippet } from './flagImplementationSnippet'
import { SDKKey } from '~/types'

export function FeatureFlagsRNInstructions(): React.ReactNode {
    return (
        <>
            <SDKInstallRNInstructions />
            <FlagImplementationSnippet sdkKey={SDKKey.REACT_NATIVE} />
        </>
    )
}

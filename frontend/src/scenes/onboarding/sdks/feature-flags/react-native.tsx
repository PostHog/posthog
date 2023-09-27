import { SDKInstallRNInstructions } from '../sdk-install-instructions'
import { FlagImplementationSnippet } from './flagImplementationSnippet'
import { SDKKey } from '~/types'

export function FeatureFlagsRNInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallRNInstructions />
            <FlagImplementationSnippet sdkKey={SDKKey.REACT_NATIVE} />
        </>
    )
}

import { SDKKey } from '~/types'
import { FlagImplementationSnippet } from './flagImplementationSnippet'
import { SDKInstallPythonInstructions } from '../sdk-install-instructions'

export function FeatureFlagsPythonInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallPythonInstructions />
            <FlagImplementationSnippet sdkKey={SDKKey.PYTHON} />
        </>
    )
}

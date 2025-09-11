import { SDKKey } from '~/types'

import { SDKInstallPythonInstructions } from '../sdk-install-instructions'
import { FlagImplementationSnippet } from './flagImplementationSnippet'

export function FeatureFlagsPythonInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallPythonInstructions />
            <FlagImplementationSnippet sdkKey={SDKKey.PYTHON} />
        </>
    )
}

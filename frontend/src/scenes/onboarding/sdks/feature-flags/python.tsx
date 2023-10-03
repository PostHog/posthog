import { SDKKey } from '~/types'
import { FlagImplementationSnippet } from './flagImplementationSnippet'
import { SDKInstallPythonInstructions } from '../sdk-install-instructions'

const FeatureFlagsPythonInstructions = (): JSX.Element => {
    return (
        <>
            <SDKInstallPythonInstructions />
            <FlagImplementationSnippet sdkKey={SDKKey.PYTHON} />
        </>
    )
}

export default { FeatureFlagsPythonInstructions }

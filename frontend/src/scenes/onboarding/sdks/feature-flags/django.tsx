import { SDKKey } from '~/types'

import { SDKInstallDjangoInstructions } from '../sdk-install-instructions'
import { FlagImplementationSnippet } from './flagImplementationSnippet'

export function FeatureFlagsDjangoInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallDjangoInstructions />
            <FlagImplementationSnippet sdkKey={SDKKey.PYTHON} />
        </>
    )
}

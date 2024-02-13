import { SDKKey } from '~/types'

import { SDKInstallFlutterInstructions } from '../sdk-install-instructions'
import { FlagImplementationSnippet } from './flagImplementationSnippet'

export function FeatureFlagsFlutterInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallFlutterInstructions />
            <FlagImplementationSnippet sdkKey={SDKKey.FLUTTER} />
        </>
    )
}

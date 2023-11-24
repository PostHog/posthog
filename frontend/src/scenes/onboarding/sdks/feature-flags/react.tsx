import { SDKKey } from '~/types'

import { SDKInstallReactInstructions } from '../sdk-install-instructions/react'
import { FlagImplementationSnippet } from './flagImplementationSnippet'

export function FeatureFlagsReactInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallReactInstructions />
            <FlagImplementationSnippet sdkKey={SDKKey.REACT} />
        </>
    )
}

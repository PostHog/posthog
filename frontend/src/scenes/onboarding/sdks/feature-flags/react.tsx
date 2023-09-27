import { FlagImplementationSnippet } from './flagImplementationSnippet'
import { SDKKey } from '~/types'
import { SDKInstallReactInstructions } from '../sdk-install-instructions/react'

export function FeatureFlagsReactInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallReactInstructions />
            <FlagImplementationSnippet sdkKey={SDKKey.REACT} />
        </>
    )
}

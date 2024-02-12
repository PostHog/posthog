import { SDKKey } from '~/types'

import { FlagImplementationSnippet } from './flagImplementationSnippet'

export function FeatureFlagsAPIInstructions(): JSX.Element {
    return (
        <>
            <FlagImplementationSnippet sdkKey={SDKKey.API} />
        </>
    )
}

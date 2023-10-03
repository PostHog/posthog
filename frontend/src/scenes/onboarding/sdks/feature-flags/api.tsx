import { SDKKey } from '~/types'
import { FlagImplementationSnippet } from './flagImplementationSnippet'

export function FeatureFlagsAPIInstructions(): React.ReactNode {
    return (
        <>
            <FlagImplementationSnippet sdkKey={SDKKey.API} />
        </>
    )
}

import { SDKKey } from '~/types'
import { FlagImplementationSnippet } from './flagImplementationSnippet'

export function ProductAnalyticsAPIInstructions(): JSX.Element {
    return (
        <>
            <FlagImplementationSnippet sdkKey={SDKKey.API} />
        </>
    )
}

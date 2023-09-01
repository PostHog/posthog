import { SDK } from '~/types'
import { productAvailableSDKs } from './sdksLogic'

export const SDKSnippet = ({ sdk, productKey }: { sdk: SDK; productKey: string }): JSX.Element => {
    const SDKInstructions = productAvailableSDKs[productKey][sdk.key]
    return SDKInstructions ? <SDKInstructions /> : <></>
}

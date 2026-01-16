import { ReactNativeInstallation } from '@posthog/shared-onboarding/product-analytics'

import { SDKKey } from '~/types'

import { AdvertiseMobileReplay } from '../session-replay/SessionReplaySDKInstructions'

export function ProductAnalyticsRNInstructions(): JSX.Element {
    return (
        <>
            <ReactNativeInstallation />
            <AdvertiseMobileReplay context="product-analytics-onboarding" sdkKey={SDKKey.REACT_NATIVE} />
        </>
    )
}

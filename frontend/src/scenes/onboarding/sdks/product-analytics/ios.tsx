import { IOSInstallation } from '@posthog/shared-onboarding/product-analytics'

import { SDKKey } from '~/types'

import { AdvertiseMobileReplay } from '../session-replay/SessionReplaySDKInstructions'

export function ProductAnalyticsIOSInstructions(): JSX.Element {
    return (
        <>
            <IOSInstallation />
            <AdvertiseMobileReplay context="product-analytics-onboarding" sdkKey={SDKKey.IOS} />
        </>
    )
}

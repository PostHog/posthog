import { AndroidInstallation } from '@posthog/shared-onboarding/product-analytics'

import { SDKKey } from '~/types'

import { AdvertiseMobileReplay } from '../session-replay/SessionReplaySDKInstructions'

export function ProductAnalyticsAndroidInstructions(): JSX.Element {
    return (
        <>
            <AndroidInstallation />
            <AdvertiseMobileReplay context="product-analytics-onboarding" sdkKey={SDKKey.ANDROID} />
        </>
    )
}

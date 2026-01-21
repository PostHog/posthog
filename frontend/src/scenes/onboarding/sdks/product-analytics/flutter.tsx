import { FlutterInstallation } from '@posthog/shared-onboarding/product-analytics'

import { SDKKey } from '~/types'

import { AdvertiseMobileReplay } from '../session-replay/SessionReplaySDKInstructions'

export function ProductAnalyticsFlutterInstructions(): JSX.Element {
    return (
        <>
            <FlutterInstallation />
            <AdvertiseMobileReplay context="product-analytics-onboarding" sdkKey={SDKKey.FLUTTER} />
        </>
    )
}

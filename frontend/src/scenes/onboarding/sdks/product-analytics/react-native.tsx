import { ReactNativeInstallation } from '@posthog/shared-onboarding/product-analytics'

import SetupWizardBanner from 'scenes/onboarding/sdks/sdk-install-instructions/components/SetupWizardBanner'

import { SDKKey } from '~/types'

import { AdvertiseMobileReplay } from '../session-replay/SessionReplaySDKInstructions'

export function ProductAnalyticsRNInstructions(): JSX.Element {
    return (
        <>
            <SetupWizardBanner integrationName="React Native" />
            <ReactNativeInstallation />
            <AdvertiseMobileReplay context="product-analytics-onboarding" sdkKey={SDKKey.REACT_NATIVE} />
        </>
    )
}

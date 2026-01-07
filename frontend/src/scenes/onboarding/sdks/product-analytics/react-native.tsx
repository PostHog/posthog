import { useValues } from 'kea'

import { LemonDivider } from '@posthog/lemon-ui'
import { ReactNativeInstallation } from '@posthog/shared-onboarding/product-analytics/react-native'

import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { OnboardingDocsContentWrapper } from 'scenes/onboarding/OnboardingDocsContentWrapper'
import SetupWizardBanner from 'scenes/onboarding/sdks/sdk-install-instructions/components/SetupWizardBanner'

export function ProductAnalyticsRNInstructions(): JSX.Element {
    const { isCloudOrDev } = useValues(preflightLogic)

    return (
        <OnboardingDocsContentWrapper>
            {isCloudOrDev && (
                <>
                    <h2>Automated installation</h2>
                    <SetupWizardBanner integrationName="React Native" />
                    <LemonDivider label="OR" />
                    <h2>Manual installation</h2>
                </>
            )}
            <ReactNativeInstallation />
        </OnboardingDocsContentWrapper>
    )
}

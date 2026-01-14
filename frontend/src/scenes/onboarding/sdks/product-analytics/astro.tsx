import { useValues } from 'kea'

import { LemonDivider } from '@posthog/lemon-ui'
import { JSEventCapture } from '@posthog/shared-onboarding/product-analytics/_snippets/js-event-capture'
import { AstroInstallation } from '@posthog/shared-onboarding/product-analytics/astro'

import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { OnboardingDocsContentWrapper } from 'scenes/onboarding/OnboardingDocsContentWrapper'
import SetupWizardBanner from 'scenes/onboarding/sdks/sdk-install-instructions/components/SetupWizardBanner'

export function ProductAnalyticsAstroInstructions(): JSX.Element {
    const { isCloudOrDev } = useValues(preflightLogic)

    return (
        <OnboardingDocsContentWrapper snippets={{ JSEventCapture }}>
            {isCloudOrDev && (
                <>
                    <h2>Automated installation</h2>
                    <SetupWizardBanner integrationName="Astro" />
                    <LemonDivider label="OR" />
                    <h2>Manual installation</h2>
                </>
            )}
            <AstroInstallation />
        </OnboardingDocsContentWrapper>
    )
}

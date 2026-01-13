import { useValues } from 'kea'

import { LemonDivider } from '@posthog/lemon-ui'
import { JSEventCapture } from '@posthog/shared-onboarding/product-analytics/_snippets/js-event-capture'
import { SvelteInstallation } from '@posthog/shared-onboarding/product-analytics/svelte'

import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { OnboardingDocsContentWrapper } from 'scenes/onboarding/OnboardingDocsContentWrapper'
import SetupWizardBanner from 'scenes/onboarding/sdks/sdk-install-instructions/components/SetupWizardBanner'

export function ProductAnalyticsSvelteJSInstructions(): JSX.Element {
    const { isCloudOrDev } = useValues(preflightLogic)

    return (
        <OnboardingDocsContentWrapper snippets={{ JSEventCapture }}>
            {isCloudOrDev && (
                <>
                    <h2>Automated installation</h2>
                    <SetupWizardBanner integrationName="Svelte" />
                    <LemonDivider label="OR" />
                    <h2>Manual installation</h2>
                </>
            )}
            <SvelteInstallation />
        </OnboardingDocsContentWrapper>
    )
}

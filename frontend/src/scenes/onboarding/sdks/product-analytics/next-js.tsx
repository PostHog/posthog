import { NextJSInstallation } from '@posthog/shared-onboarding/product-analytics'

import SetupWizardBanner from 'scenes/onboarding/sdks/sdk-install-instructions/components/SetupWizardBanner'

export function ProductAnalyticsNextJSInstructions(): JSX.Element {
    return (
        <>
            <SetupWizardBanner integrationName="Next.js" />
            <NextJSInstallation />
        </>
    )
}

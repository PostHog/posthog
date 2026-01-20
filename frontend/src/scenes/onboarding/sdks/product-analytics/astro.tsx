import { AstroInstallation } from '@posthog/shared-onboarding/product-analytics'

import SetupWizardBanner from 'scenes/onboarding/sdks/sdk-install-instructions/components/SetupWizardBanner'

export function ProductAnalyticsAstroInstructions(): JSX.Element {
    return (
        <>
            <SetupWizardBanner integrationName="Astro" />
            <AstroInstallation />
        </>
    )
}

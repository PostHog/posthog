import { DjangoInstallation } from '@posthog/shared-onboarding/product-analytics'

import SetupWizardBanner from 'scenes/onboarding/sdks/sdk-install-instructions/components/SetupWizardBanner'

export function ProductAnalyticsDjangoInstructions(): JSX.Element {
    return (
        <>
            <SetupWizardBanner integrationName="Django" />
            <DjangoInstallation />
        </>
    )
}

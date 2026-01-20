import { TanStackInstallation } from '@posthog/shared-onboarding/product-analytics'

import SetupWizardBanner from 'scenes/onboarding/sdks/sdk-install-instructions/components/SetupWizardBanner'

export function ProductAnalyticsTanStackInstructions(): JSX.Element {
    return (
        <>
            <SetupWizardBanner integrationName="React" />
            <TanStackInstallation />
        </>
    )
}

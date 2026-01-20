import { ReactInstallation } from '@posthog/shared-onboarding/product-analytics'

import SetupWizardBanner from 'scenes/onboarding/sdks/sdk-install-instructions/components/SetupWizardBanner'

export function ProductAnalyticsReactInstructions(): JSX.Element {
    return (
        <>
            <SetupWizardBanner integrationName="React" />
            <ReactInstallation />
        </>
    )
}

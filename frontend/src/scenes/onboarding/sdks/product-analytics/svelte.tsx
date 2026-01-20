import { SvelteInstallation } from '@posthog/shared-onboarding/product-analytics'

import SetupWizardBanner from 'scenes/onboarding/sdks/sdk-install-instructions/components/SetupWizardBanner'

export function ProductAnalyticsSvelteJSInstructions(): JSX.Element {
    return (
        <>
            <SetupWizardBanner integrationName="Svelte" />
            <SvelteInstallation />
        </>
    )
}

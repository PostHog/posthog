import { useValues } from 'kea'

import { LemonDivider } from '@posthog/lemon-ui'
import { DjangoInstallation } from '@posthog/shared-onboarding/product-analytics'

import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import SetupWizardBanner from 'scenes/onboarding/sdks/sdk-install-instructions/components/SetupWizardBanner'

export function ProductAnalyticsDjangoInstructions(): JSX.Element {
    const { isCloudOrDev } = useValues(preflightLogic)

    return (
        <>
            {isCloudOrDev && (
                <>
                    <h2>Automated installation</h2>
                    <SetupWizardBanner integrationName="Django" />
                    <LemonDivider label="OR" />
                    <h2>Manual installation</h2>
                </>
            )}
            <DjangoInstallation />
        </>
    )
}

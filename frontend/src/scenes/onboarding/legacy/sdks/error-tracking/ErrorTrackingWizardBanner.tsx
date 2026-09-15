import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import SetupWizardBanner from 'scenes/onboarding/shared/SetupWizardBanner'

/**
 * The automated-install banner above the error tracking SDK instructions. The dedicated
 * `error-tracking` wizard subcommand is still rolling out, so the banner keeps the base SDK
 * install command while its flag is off.
 */
export function ErrorTrackingWizardBanner({ integrationName }: { integrationName: string }): JSX.Element | null {
    const hasNewWizard = useFeatureFlag('ERROR_TRACKING_NEW_WIZARD')
    if (!hasNewWizard) {
        return <SetupWizardBanner integrationName={integrationName} />
    }
    return (
        <SetupWizardBanner
            integrationName={integrationName}
            subcommand="error-tracking"
            description="Wizard sets up error tracking for you. The setup agent installs the SDK if needed, then adds exception capture and source map upload."
        />
    )
}

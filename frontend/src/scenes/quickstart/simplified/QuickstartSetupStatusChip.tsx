import { useActions } from 'kea'

import { IconWarning } from '@posthog/icons'
import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { wizardSyncUiLogic } from 'scenes/onboarding/shared/wizard-sync/wizardSyncUiLogic'

import { QuickstartWizardProgress } from '../shared/QuickstartWizardProgress'

/** Header install status for the simplified page. The full status lives in the focused
 * install view behind Back to setup, so this only needs to say a run is happening. */
export function QuickstartSetupStatusChip({
    installationComplete,
    installDismissed,
    onReopen,
}: {
    installationComplete: boolean
    installDismissed: boolean
    onReopen: () => void
}): JSX.Element {
    const { openDialog } = useActions(wizardSyncUiLogic)

    return (
        <QuickstartWizardProgress
            fallback={
                !installationComplete && installDismissed ? (
                    <LemonButton size="small" onClick={onReopen} data-attr="quickstart-back-to-setup">
                        Back to setup
                    </LemonButton>
                ) : null
            }
        >
            {(progress) => (
                <LemonButton
                    size="small"
                    icon={progress.error ? <IconWarning className="text-danger" /> : <Spinner />}
                    onClick={installationComplete ? openDialog : onReopen}
                    data-attr="quickstart-setup-status-chip"
                >
                    {progress.error ? 'Setup needs attention' : 'Setting up PostHog'}
                </LemonButton>
            )}
        </QuickstartWizardProgress>
    )
}

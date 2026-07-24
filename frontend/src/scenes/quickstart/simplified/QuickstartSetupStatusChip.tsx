import { useActions } from 'kea'

import { IconCheckCircle, IconPullRequest, IconWarning } from '@posthog/icons'
import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { syncHeadline } from 'scenes/onboarding/shared/wizard-sync/helpers'
import { InstallationProgress } from 'scenes/onboarding/shared/wizard-sync/installationProgressLogic'
import { wizardSyncUiLogic } from 'scenes/onboarding/shared/wizard-sync/wizardSyncUiLogic'

import { captureQuickstartAction } from '../shared/captureQuickstartAction'
import { QuickstartWizardProgress } from '../shared/QuickstartWizardProgress'

function chipIcon(progress: InstallationProgress): JSX.Element {
    if (progress.phase === 'completed') {
        return <IconCheckCircle className="text-success" />
    }
    if (progress.phase === 'error') {
        return <IconWarning className="text-danger" />
    }
    if (progress.prUrl) {
        return <IconPullRequest className="text-purple" />
    }
    return <Spinner />
}

/** Header install status for the simplified page. The full status lives in the focused
 * install view behind Back to setup, so this only needs the run's headline state. */
export function QuickstartSetupStatusChip({
    installationComplete,
    installDismissed,
    onReopen,
}: {
    installationComplete: boolean
    installDismissed: boolean
    /** Reopens the focused install view; the source distinguishes the chip from the plain button */
    onReopen: (source: string) => void
}): JSX.Element {
    const { openDialog } = useActions(wizardSyncUiLogic)

    return (
        <QuickstartWizardProgress
            fallback={
                !installationComplete && installDismissed ? (
                    <LemonButton
                        size="small"
                        onClick={() => onReopen('back_to_setup_button')}
                        data-attr="quickstart-back-to-setup"
                    >
                        Back to setup
                    </LemonButton>
                ) : null
            }
        >
            {(progress) => (
                <LemonButton
                    size="small"
                    icon={chipIcon(progress)}
                    onClick={() => {
                        if (installationComplete) {
                            captureQuickstartAction('view_setup_status')
                            openDialog()
                        } else {
                            onReopen('setup_status_chip')
                        }
                    }}
                    data-attr="quickstart-setup-status-chip"
                >
                    {syncHeadline(progress)}
                </LemonButton>
            )}
        </QuickstartWizardProgress>
    )
}

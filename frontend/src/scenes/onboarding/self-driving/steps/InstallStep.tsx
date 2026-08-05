import { useLocalWizardRunActive } from 'scenes/onboarding/shared/wizard-sync/hooks'
import { InstallationProgressView } from 'scenes/onboarding/shared/wizard-sync/InstallationProgressView'
import { SELF_DRIVING_WORKFLOW_ID } from 'scenes/onboarding/shared/wizard-sync/workflows'

import { SelfDrivingInstallOptions } from '../components/SelfDrivingInstallOptions'

/**
 * The step swaps to the live tracker as soon as the CLI registers a run. Sync is unconditional here
 * (no `ONBOARDING_WIZARD_SYNC` gate): without it this step is a static command with no feedback, and
 * watching the run is the whole point of the flow. There is no cloud run to coordinate with, so the
 * local session stream is the only source.
 */
export function InstallStep({ onContinue }: { onContinue: () => void }): JSX.Element {
    const isLocalRunActive = useLocalWizardRunActive(SELF_DRIVING_WORKFLOW_ID)
    return isLocalRunActive ? (
        <InstallationProgressView
            mode="local"
            workflowId={SELF_DRIVING_WORKFLOW_ID}
            continueHint="Keep answering the wizard in your terminal. Progress shows up here as it goes, so you can carry on with the rest of onboarding whenever you like."
        />
    ) : (
        <SelfDrivingInstallOptions onContinue={onContinue} />
    )
}

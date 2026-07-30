import { useActions } from 'kea'

import { IconCheckCircle } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { onboardingEventUsageLogic } from 'scenes/onboarding/onboardingEventUsageLogic'
import { useWizardCommand } from 'scenes/onboarding/shared/useWizardCommand'
import { useLocalWizardRunActive } from 'scenes/onboarding/shared/wizard-sync/hooks'
import { InstallationProgressView } from 'scenes/onboarding/shared/wizard-sync/InstallationProgressView'
import { WizardCommandBlock } from 'scenes/onboarding/shared/wizard-sync/WizardCommandBlock'
import { WizardInstallOptions } from 'scenes/onboarding/shared/wizard-sync/WizardInstallOptions'
import { SELF_DRIVING_WORKFLOW_ID } from 'scenes/onboarding/shared/wizard-sync/workflows'

/** What the self-driving run wires up, so the command isn't a leap of faith. */
const WIZARD_SETS_UP = [
    'Connects your GitHub, so agents can open pull requests',
    'Picks the signal sources and scouts worth watching',
    'Sends findings to your inbox as they land',
]

// The self-driving run is interactive: it asks about your issue tracker, walks you through the
// GitHub App install, and proposes scouts. The cloud runner can't do any of that (it runs headless
// and the CLI rejects `--ci` for this program), so the cloud arm is forced off here rather than
// being left to the experiment flag.
function SelfDrivingInstallOptions({ onContinue }: { onContinue: () => void }): JSX.Element {
    const { isCloudOrDev } = useWizardCommand()
    const { reportSelfDrivingOnboardingInstallModeSelected } = useActions(onboardingEventUsageLogic)

    // Self-hosted: the wizard CLI only targets cloud + dev, so the command block renders nothing.
    // Show a real, actionable fallback instead of an empty step.
    if (!isCloudOrDev) {
        return (
            <div className="flex flex-col gap-3">
                <p className="text-sm text-muted m-0">
                    Install the PostHog SDK for your framework and your product's context starts flowing in, ready for
                    agents to act on.
                </p>
                <LemonButton type="primary" to="https://posthog.com/docs/getting-started/install" targetBlank>
                    Read the install docs
                </LemonButton>
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-4">
            <p className="text-sm text-muted text-center m-0">
                Run this in your project. It sets everything up and hands back an inbox that's already working.
            </p>
            <WizardInstallOptions
                hideHog
                offerCloudRun={false}
                onQueued={onContinue}
                onModeSelected={reportSelfDrivingOnboardingInstallModeSelected}
                localBlock={
                    <WizardCommandBlock
                        hideHog
                        subcommand="self-driving"
                        description="Takes about ten minutes. It'll ask you a few things along the way."
                    />
                }
            />
            <ul className="flex flex-col gap-1.5 m-0 p-0 list-none">
                {WIZARD_SETS_UP.map((line) => (
                    <li key={line} className="flex items-start gap-2">
                        <IconCheckCircle className="size-4 text-success shrink-0 mt-0.5" />
                        <span className="text-xs text-muted">{line}</span>
                    </li>
                ))}
            </ul>
        </div>
    )
}

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

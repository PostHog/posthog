import { SelfDrivingInstallOptions } from '../components/SelfDrivingInstallOptions'

/**
 * Sync is unconditional here (no `ONBOARDING_WIZARD_SYNC` gate): without it this step is a static
 * command with no feedback, and watching the run is the whole point of the flow. Once the CLI
 * registers a run, the install options swap the command block for the compact tracker.
 */
export function InstallStep({ onContinue }: { onContinue: () => void }): JSX.Element {
    return <SelfDrivingInstallOptions onContinue={onContinue} />
}

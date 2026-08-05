import { useValues } from 'kea'

import { useLocalWizardRunActive } from 'scenes/onboarding/shared/wizard-sync/hooks'
import { InstallationProgressView } from 'scenes/onboarding/shared/wizard-sync/InstallationProgressView'
import { SELF_DRIVING_WORKFLOW_ID } from 'scenes/onboarding/shared/wizard-sync/workflows'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'

import { SelfDrivingInstallOptions } from '../components/SelfDrivingInstallOptions'
import { SELF_DRIVING_TOOLS, toolSetForGoal } from '../goals'
import { goalSelectionLogic } from '../goalSelectionLogic'

/** A quiet reminder of what the install feeds: the goal's tool set, as icons and names. */
function ProductsBeingInstalled(): JSX.Element {
    const { selectedGoal } = useValues(goalSelectionLogic)
    const tools = toolSetForGoal(selectedGoal).shown.map((key) => SELF_DRIVING_TOOLS[key])
    return (
        <div className="flex flex-wrap items-center justify-center gap-x-3 gap-y-1 text-xs text-muted">
            <span>Installing:</span>
            {tools.map((tool) => (
                <span key={tool.name} className="flex items-center gap-1">
                    <span className="flex text-sm group/colorful-product-icons colorful-product-icons-true">
                        {iconForType(tool.iconType)}
                    </span>
                    {tool.name}
                </span>
            ))}
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
    return (
        <div className="flex flex-col gap-4">
            {isLocalRunActive ? (
                <InstallationProgressView
                    mode="local"
                    workflowId={SELF_DRIVING_WORKFLOW_ID}
                    continueHint="Keep answering the wizard in your terminal. Progress shows up here as it goes, so you can carry on with the rest of onboarding whenever you like."
                />
            ) : (
                <SelfDrivingInstallOptions onContinue={onContinue} />
            )}
            <ProductsBeingInstalled />
        </div>
    )
}

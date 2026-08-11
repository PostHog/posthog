import { useActions, useValues } from 'kea'

import { IconCheckCircle } from '@posthog/icons'
import { LemonButton, Link } from '@posthog/lemon-ui'

import { onboardingEventUsageLogic } from 'scenes/onboarding/onboardingEventUsageLogic'
import { CheckList } from 'scenes/onboarding/shared/components/CheckList'
import { useWizardCommand } from 'scenes/onboarding/shared/useWizardCommand'
import { useLocalWizardRunActive } from 'scenes/onboarding/shared/wizard-sync/hooks'
import { WizardCommandBlock } from 'scenes/onboarding/shared/wizard-sync/WizardCommandBlock'
import { WizardInstallOptions } from 'scenes/onboarding/shared/wizard-sync/WizardInstallOptions'
import { SELF_DRIVING_WORKFLOW_ID } from 'scenes/onboarding/shared/wizard-sync/workflows'
import { urls } from 'scenes/urls'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'

import { DOCS_URL_BY_PRODUCT_PATH, ONBOARDING_TOOLS, resolveSetup, toolIconType } from '../../shared/useCases'
import { useCaseSelectionLogic } from '../useCaseSelectionLogic'
import { InstallationTracker } from './InstallationTracker'

/** A quiet reminder of what the install feeds: the use case's tools, as icons and names. */
function ProductsBeingInstalled(): JSX.Element {
    const { selectedUseCase } = useValues(useCaseSelectionLogic)
    const tools = resolveSetup(selectedUseCase).tools.map((key) => ONBOARDING_TOOLS[key])
    return (
        <div className="flex flex-wrap items-center justify-center gap-x-3 gap-y-1 text-xs text-muted">
            <span>Tools for your setup:</span>
            {tools.map((tool) => (
                <Link
                    key={tool.productPath}
                    to={DOCS_URL_BY_PRODUCT_PATH[tool.productPath]}
                    target="_blank"
                    className="flex items-center gap-1 text-muted hover:text-default"
                >
                    <span className="flex text-sm group/colorful-product-icons colorful-product-icons-true">
                        {iconForType(toolIconType(tool))}
                    </span>
                    {tool.displayName ?? tool.productPath}
                </Link>
            ))}
        </div>
    )
}

/** What the self-driving run wires up, so the command isn't a leap of faith. */
const WIZARD_SETS_UP = [
    'Installs the SDK and wires up event capture',
    'Connects GitHub so agents can open pull requests',
    'Sets up scouts that send findings to your Inbox',
]

// The self-driving run is interactive: it asks about your issue tracker, walks you through the
// GitHub App install, and proposes scouts. The cloud runner can't do any of that (it runs headless
// and the CLI rejects `--ci` for this program), so the cloud arm is forced off here rather than
// being left to the experiment flag.
export function SelfDrivingInstallOptions({ onContinue }: { onContinue: () => void }): JSX.Element {
    const { isCloudOrDev } = useWizardCommand()
    const { reportOnboardingInstallModeSelected, reportOnboardingSelfDrivingExplainerClicked } =
        useActions(onboardingEventUsageLogic)
    // Once the CLI registers a run, the command block and its caption give way to the tracker -
    // the command has been run, so repeating it is noise.
    const isRunActive = useLocalWizardRunActive(SELF_DRIVING_WORKFLOW_ID)

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
                Run this command in your project. The setup agent detects your framework, installs the SDK, and starts
                capturing events.{' '}
                <Link
                    to="https://posthog.com/self-driving"
                    target="_blank"
                    onClick={() => reportOnboardingSelfDrivingExplainerClicked('install')}
                    data-attr="self-driving-explainer-link"
                >
                    What is self-driving?
                </Link>
            </p>
            <WizardInstallOptions
                hideHog
                offerCloudRun={false}
                onQueued={onContinue}
                onModeSelected={reportOnboardingInstallModeSelected}
                localBlock={
                    <div className="flex flex-col gap-2">
                        {isRunActive ? (
                            <InstallationTracker variant="card" />
                        ) : (
                            <WizardCommandBlock
                                hideHog
                                subcommand="self-driving"
                                description="About ten minutes: a few questions up front, then the agent does the rest."
                            />
                        )}
                        <ProductsBeingInstalled />
                    </div>
                }
            />
            <div className="flex justify-center">
                <CheckList
                    size="xs"
                    items={WIZARD_SETS_UP.map((line) => ({
                        icon: <IconCheckCircle />,
                        content: <span className="text-muted">{line}</span>,
                    }))}
                />
            </div>
        </div>
    )
}

/** The manual escape hatch, rendered by the flow footer next to Continue on the install step. */
export function ManualSetupButton(): JSX.Element {
    const { reportOnboardingInstallModeSelected } = useActions(onboardingEventUsageLogic)
    // New tab so the step, and its verification, stays open while they follow the instructions.
    return (
        <LemonButton
            type="tertiary"
            size="small"
            to={urls.settings('environment-details', 'snippet')}
            targetBlank
            onClick={() => reportOnboardingInstallModeSelected('manual')}
            data-attr="self-driving-manual-setup"
        >
            Need to set up manually?
        </LemonButton>
    )
}

import { useActions, useValues } from 'kea'

import { LemonButton, LemonModal, Link } from '@posthog/lemon-ui'

import { OnboardingStepKey, type SDK } from '~/types'

import { onboardingEventUsageLogic } from '../../../onboardingEventUsageLogic'
import { OnboardingStep } from '../../../OnboardingStep'
import { activeCloudRunLogic } from '../../../shared/wizard-sync/activeCloudRunLogic'
import { useLocalWizardRunActive } from '../../../shared/wizard-sync/hooks'
import { InstallationProgressView } from '../../../shared/wizard-sync/InstallationProgressView'
import { WizardCommandBlock } from '../../../shared/wizard-sync/WizardCommandBlock'
import { WizardFrameworkIcons } from '../../../shared/wizard-sync/WizardFrameworkIcons'
import { WizardInstallOptions } from '../../../shared/wizard-sync/WizardInstallOptions'
import { WizardFrameworkBadges, WizardModeShell } from '../../../shared/wizard-sync/WizardModeShell'
import { AdblockWarning, RealtimeCheckIndicator } from '../../RealtimeCheckIndicator'
import { SDKGrid } from '../SDKGrid'
import { SDKInstructionsModal } from '../SDKInstructionsModal'
import { VariantProps, WizardOverrides } from '../types'
import { wizardInstallStepLogic } from '../wizardInstallStepLogic'
import { WizardInstallIntro } from './WizardInstallIntro'

// The shared cloud/local switcher wrapped with onboarding's own command block and instrumentation.
// An active cloud run renders inside it (WizardCloudRunBlock pins to the run's progress), so the
// failed-run "Run it yourself" fallback keeps working — the mode state must not unmount mid-recovery.
function OnboardingInstallOptions({
    wizardOverrides,
    compact = false,
}: {
    wizardOverrides?: WizardOverrides
    compact?: boolean
}): JSX.Element {
    const { reportOnboardingInstallModeSelected } = useActions(onboardingEventUsageLogic)
    return (
        <WizardInstallOptions
            onModeSelected={reportOnboardingInstallModeSelected}
            // The cloud runner only executes the base integration program, not dedicated subcommands,
            // so a dedicated-program step neither offers a run nor lets one queued elsewhere take over.
            offerCloudRun={!wizardOverrides}
            ignoreActiveCloudRun={!!wizardOverrides}
            hog={compact ? null : undefined}
            badges={
                wizardOverrides?.supports ? (
                    <WizardFrameworkBadges items={wizardOverrides.supports} />
                ) : compact ? (
                    <WizardFrameworkIcons />
                ) : undefined
            }
            localBlock={
                <WizardCommandBlock
                    subcommand={wizardOverrides?.subcommand}
                    description={
                        wizardOverrides?.description ??
                        (compact ? 'Run this in your project folder. No API key needed.' : undefined)
                    }
                    hog={compact ? null : undefined}
                />
            }
        />
    )
}

/**
 * Default install step for non-Logs onboarding flows. Wizard-centered: the SDK
 * grid lives behind a "Need to set up manually?" link.
 *
 * Owns its own SDKInstructionsModal because the manual-setup flow is nested —
 * picking an SDK in the manual modal closes it and opens the instructions
 * modal; closing the instructions modal reopens manual setup. The shared modal
 * in the parent OnboardingInstallStep is skipped here.
 *
 * A live local wizard run takes over the step, and an in-flight run (cloud or local) unblocks
 * Continue without waiting for installation events.
 */
export function WizardInstallStep(props: VariantProps): JSX.Element {
    const isLocalRunActive = useLocalWizardRunActive()
    const { setManualModalOpen } = useActions(wizardInstallStepLogic)
    // Deliberately not gated on the cloud-run flag: a persisted handle is proof the user started a
    // run while on the test arm, and a mid-experiment flag change must not strand an in-flight run.
    // A dedicated-program step ignores it, because the run only executes the base program.
    const { activeCloudRun: persistedCloudRun } = useValues(activeCloudRunLogic)
    const activeCloudRun = props.wizardOverrides ? null : persistedCloudRun
    // Once the wizard is in flight (cloud or local), trust it — installation events aren't required
    // to unblock Continue.
    const continueDisabledReason =
        isLocalRunActive || activeCloudRun || props.installationComplete ? undefined : 'Installation is not complete'
    // A cloud run wins over the local run view: the cloud wizard posts to the same session stream, so
    // rendering both would show the same run twice. The cloud run's progress renders inside
    // OnboardingInstallOptions (WizardCloudRunBlock pins to it).
    const runView = activeCloudRun ? (
        <OnboardingInstallOptions wizardOverrides={props.wizardOverrides} compact={props.compact} />
    ) : isLocalRunActive ? (
        <InstallationProgressView mode="local" />
    ) : null
    return (
        <WizardInstallShell
            continueDisabledReason={continueDisabledReason}
            showSkip={!props.installationComplete && !isLocalRunActive && !activeCloudRun}
            props={props}
        >
            {props.compact ? (
                <WizardModeShell data-attr="wizard-install-compact">
                    {runView ?? (
                        <>
                            <p className="text-muted mb-0">
                                {props.wizardOverrides?.intro ??
                                    'Wizard is a setup agent. It detects your framework, installs the SDK, and adds your project token to your environment variables.'}
                            </p>
                            <OnboardingInstallOptions wizardOverrides={props.wizardOverrides} compact />
                        </>
                    )}
                    <Link
                        className="self-start text-sm"
                        data-attr="sdk-continue"
                        onClick={() => setManualModalOpen(true)}
                    >
                        Want to set up manually?
                    </Link>
                </WizardModeShell>
            ) : runView ? (
                <div className="max-w-xl mx-auto">{runView}</div>
            ) : (
                <>
                    <WizardInstallIntro description={props.wizardOverrides?.intro} />
                    <div className="max-w-xl mx-auto">
                        <OnboardingInstallOptions wizardOverrides={props.wizardOverrides} />
                    </div>
                </>
            )}
        </WizardInstallShell>
    )
}

function WizardInstallShell({
    children,
    continueDisabledReason,
    showSkip,
    props,
}: {
    children: React.ReactNode
    continueDisabledReason: string | undefined
    showSkip: boolean
    props: VariantProps
}): JSX.Element {
    const { manualModalOpen, sdkInstructionsOpen } = useValues(wizardInstallStepLogic)
    const { setManualModalOpen, setSdkInstructionsOpen } = useActions(wizardInstallStepLogic)
    const {
        sdkGridProps,
        sdkInstructionMap,
        adblockResult,
        installationComplete,
        listeningForName,
        teamPropertyToVerify,
        selectedSDK,
        header,
    } = props

    const handleManualSDKClick = (sdk: SDK): void => {
        sdkGridProps.onSDKClick(sdk)
        setManualModalOpen(false)
        setSdkInstructionsOpen(true)
    }

    return (
        <OnboardingStep
            title={props.installTitle}
            subtitle={props.installSubtitle}
            stepKey={OnboardingStepKey.INSTALL}
            continueDisabledReason={continueDisabledReason}
            showSkip={showSkip}
            actions={
                <div className="pr-2 min-w-0">
                    <RealtimeCheckIndicator
                        teamPropertyToVerify={teamPropertyToVerify}
                        listeningForName={listeningForName}
                    />
                </div>
            }
        >
            {header}
            {!installationComplete && <AdblockWarning adblockResult={adblockResult} />}
            <div className="mt-6 space-y-8">
                {children}
                {/* The compact layout puts this link in the Wizard column instead. */}
                {!props.compact && (
                    <div className="flex justify-center">
                        <LemonButton
                            type="tertiary"
                            size="small"
                            data-attr="sdk-continue"
                            onClick={() => setManualModalOpen(true)}
                        >
                            Need to set up manually?
                        </LemonButton>
                    </div>
                )}
            </div>

            <LemonModal
                isOpen={manualModalOpen}
                onClose={() => setManualModalOpen(false)}
                title="Manual SDK setup"
                width="80vw"
            >
                <div className="p-4">
                    <SDKGrid {...{ ...sdkGridProps, onSDKClick: handleManualSDKClick }} showTopControls />
                </div>
            </LemonModal>

            {selectedSDK && (
                <SDKInstructionsModal
                    isOpen={sdkInstructionsOpen && !manualModalOpen}
                    onClose={() => {
                        setSdkInstructionsOpen(false)
                        setManualModalOpen(true)
                    }}
                    sdk={selectedSDK}
                    sdkInstructionMap={sdkInstructionMap}
                    adblockResult={adblockResult}
                    verifyingProperty={teamPropertyToVerify}
                    verifyingName={listeningForName}
                />
            )}
        </OnboardingStep>
    )
}

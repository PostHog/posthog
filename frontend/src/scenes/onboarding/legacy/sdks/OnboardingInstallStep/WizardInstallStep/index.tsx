import { useActions, useValues } from 'kea'

import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { OnboardingStepKey, type SDK } from '~/types'

import { onboardingEventUsageLogic } from '../../../../onboardingEventUsageLogic'
import { activeCloudRunLogic } from '../../../../shared/wizard-sync/activeCloudRunLogic'
import { useLocalWizardRunActive } from '../../../../shared/wizard-sync/hooks'
import { InstallationProgressView } from '../../../../shared/wizard-sync/InstallationProgressView'
import { WizardCommandBlock } from '../../../../shared/wizard-sync/WizardCommandBlock'
import { WizardInstallOptions } from '../../../../shared/wizard-sync/WizardInstallOptions'
import { WizardFrameworkBadges } from '../../../../shared/wizard-sync/WizardModeShell'
import { OnboardingStep } from '../../../OnboardingStep'
import { AdblockWarning, RealtimeCheckIndicator } from '../../RealtimeCheckIndicator'
import { SDKGrid } from '../SDKGrid'
import { SDKInstructionsModal } from '../SDKInstructionsModal'
import { VariantProps, WizardOverrides } from '../types'
import { wizardInstallStepLogic } from '../wizardInstallStepLogic'
import { WizardInstallIntro } from './WizardInstallIntro'

// The shared cloud/local switcher wrapped with legacy's own command block and instrumentation. An
// active cloud run renders inside it (WizardCloudRunBlock pins to the run's progress), so the
// failed-run "Run it yourself" fallback keeps working — the mode state must not unmount mid-recovery.
function LegacyInstallOptions({ wizardOverrides }: { wizardOverrides?: WizardOverrides }): JSX.Element {
    const { reportOnboardingInstallModeSelected } = useActions(onboardingEventUsageLogic)
    return (
        <WizardInstallOptions
            onModeSelected={reportOnboardingInstallModeSelected}
            // The cloud runner only executes the base integration program, not dedicated subcommands,
            // so a dedicated-program step neither offers a run nor lets one queued elsewhere take over.
            offerCloudRun={!wizardOverrides}
            ignoreActiveCloudRun={!!wizardOverrides}
            badges={wizardOverrides?.supports ? <WizardFrameworkBadges items={wizardOverrides.supports} /> : undefined}
            localBlock={
                <WizardCommandBlock
                    subcommand={wizardOverrides?.subcommand}
                    description={wizardOverrides?.description}
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
 * Sync features (live wizard takeover banner, Continue-unblock on session) are
 * gated on `ONBOARDING_WIZARD_SYNC=test` so the kea logic and its SSE only
 * mount for the test arm.
 */
export function WizardInstallStep(props: VariantProps): JSX.Element {
    const isSyncEnabled = useFeatureFlag('ONBOARDING_WIZARD_SYNC', 'test')
    return isSyncEnabled ? <WizardInstallStepWithSync {...props} /> : <WizardInstallStepStatic {...props} />
}

function WizardInstallStepStatic(props: VariantProps): JSX.Element {
    // Deliberately not gated on the cloud-run flag: a persisted handle is proof the user started a
    // run while on the test arm, and a mid-experiment flag change must not strand an in-flight run.
    const { activeCloudRun: persistedCloudRun } = useValues(activeCloudRunLogic)
    // A run queued on another step only executes the base program, so a dedicated-program step
    // (wizardOverrides) ignores it: its command stays visible and Continue stays gated.
    const activeCloudRun = props.wizardOverrides ? null : persistedCloudRun
    // A queued/running cloud run unblocks Continue just like a local takeover: the run keeps going
    // in the background (surfaced by the FAB) and installation events aren't required.
    const continueDisabledReason =
        props.installationComplete || activeCloudRun ? undefined : 'Installation is not complete'
    return (
        <WizardInstallShell
            continueDisabledReason={continueDisabledReason}
            showSkip={!props.installationComplete && !activeCloudRun}
            props={props}
        >
            {/* The intro's terminal framing makes no sense while a run's progress is on screen. */}
            {!activeCloudRun && <WizardInstallIntro description={props.wizardOverrides?.intro} />}
            <div className="max-w-xl mx-auto">
                <LegacyInstallOptions wizardOverrides={props.wizardOverrides} />
            </div>
        </WizardInstallShell>
    )
}

function WizardInstallStepWithSync(props: VariantProps): JSX.Element {
    const isLocalRunActive = useLocalWizardRunActive()
    // See WizardInstallStepStatic: an existing handle renders regardless of the experiment arm,
    // but a dedicated-program step ignores it (the run only executes the base program).
    const { activeCloudRun: persistedCloudRun } = useValues(activeCloudRunLogic)
    const activeCloudRun = props.wizardOverrides ? null : persistedCloudRun
    // Once the wizard is in flight (cloud or local), trust it — installation events aren't required
    // to unblock Continue.
    const continueDisabledReason =
        isLocalRunActive || activeCloudRun || props.installationComplete ? undefined : 'Installation is not complete'
    return (
        <WizardInstallShell
            continueDisabledReason={continueDisabledReason}
            showSkip={!props.installationComplete && !isLocalRunActive && !activeCloudRun}
            props={props}
        >
            {/* A cloud run wins over the local run view: the cloud wizard posts to the same session
                stream, so rendering both would show the same run twice. The cloud run's progress
                renders inside LegacyInstallOptions (WizardCloudRunBlock pins to it). */}
            {activeCloudRun ? (
                <div className="max-w-xl mx-auto">
                    <LegacyInstallOptions wizardOverrides={props.wizardOverrides} />
                </div>
            ) : isLocalRunActive ? (
                <div className="max-w-xl mx-auto">
                    <InstallationProgressView mode="local" />
                </div>
            ) : (
                <>
                    <WizardInstallIntro description={props.wizardOverrides?.intro} />
                    <div className="max-w-xl mx-auto">
                        <LegacyInstallOptions wizardOverrides={props.wizardOverrides} />
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
                <div className="text-center">
                    <LemonButton
                        type="tertiary"
                        size="small"
                        data-attr="sdk-continue"
                        onClick={() => setManualModalOpen(true)}
                    >
                        Need to set up manually?
                    </LemonButton>
                </div>
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

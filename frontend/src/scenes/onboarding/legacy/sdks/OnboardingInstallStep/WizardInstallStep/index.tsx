import { useActions, useValues } from 'kea'

import { IconInfo } from '@posthog/icons'
import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { OnboardingStepKey, type SDK } from '~/types'

import { OnboardingStep } from '../../../OnboardingStep'
import { useVerificationStalled } from '../../hooks/useInstallationComplete'
import { AdblockWarning, RealtimeCheckIndicator } from '../../RealtimeCheckIndicator'
import { SDKGrid } from '../SDKGrid'
import { SDKInstructionsModal } from '../SDKInstructionsModal'
import { VariantProps } from '../types'
import { WizardCommandBlock } from '../WizardCommandBlock'
import { wizardInstallStepLogic } from '../wizardInstallStepLogic'
import { WizardProgressTracker, useWizardTakeoverActive } from '../WizardProgressTracker'
import { WizardInstallIntro } from './WizardInstallIntro'

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
    // After an extended wait, stop trapping users behind a disabled Continue — the
    // "Waiting for…" check may never resolve for their setup, so let them proceed.
    const stalled = useVerificationStalled(props.installationComplete)
    const canContinue = props.installationComplete || stalled
    const continueDisabledReason = canContinue ? undefined : 'Installation is not complete'
    return (
        <WizardInstallShell
            continueDisabledReason={continueDisabledReason}
            showSkip={!props.installationComplete}
            props={props}
        >
            <WizardInstallIntro />
            <div className="max-w-xl mx-auto">
                <WizardCommandBlock />
            </div>
            {stalled && !props.installationComplete && (
                <VerificationStalledHint listeningForName={props.listeningForName} />
            )}
        </WizardInstallShell>
    )
}

function WizardInstallStepWithSync(props: VariantProps): JSX.Element {
    const isTakeoverActive = useWizardTakeoverActive()
    // Once the wizard is in flight, trust it — installation events aren't required
    // to unblock Continue. Otherwise fall back to the same stall escape hatch as the
    // static arm so a never-resolving check can't trap users.
    const stalled = useVerificationStalled(props.installationComplete)
    const canContinue = isTakeoverActive || props.installationComplete || stalled
    const continueDisabledReason = canContinue ? undefined : 'Installation is not complete'
    return (
        <WizardInstallShell
            continueDisabledReason={continueDisabledReason}
            showSkip={!props.installationComplete && !isTakeoverActive}
            props={props}
        >
            {isTakeoverActive ? (
                <WizardProgressTracker />
            ) : (
                <>
                    <WizardInstallIntro />
                    <div className="max-w-xl mx-auto">
                        <WizardCommandBlock />
                    </div>
                    {stalled && !props.installationComplete && (
                        <VerificationStalledHint listeningForName={props.listeningForName} />
                    )}
                </>
            )}
        </WizardInstallShell>
    )
}

/**
 * Shown once verification has been waiting a while without an event landing. Points
 * users at the now-enabled Continue button so they aren't stuck copying the command
 * with no visible way forward.
 */
function VerificationStalledHint({ listeningForName }: { listeningForName?: string }): JSX.Element {
    return (
        <div className="max-w-xl mx-auto flex items-start gap-2 px-3 py-2 rounded border border-border bg-bg-light text-sm">
            <IconInfo className="text-muted mt-0.5 shrink-0" />
            <span>
                Still waiting for your first {listeningForName ?? 'event'}? Once you've run the command it can take a
                moment to arrive — you can continue setup now and we'll keep checking in the background.
            </span>
        </div>
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
            title="Install"
            stepKey={OnboardingStepKey.INSTALL}
            continueDisabledReason={continueDisabledReason}
            showSkip={showSkip}
            actions={
                <div className="pr-2">
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

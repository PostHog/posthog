import { useActions, useValues } from 'kea'
import { useCallback, useState } from 'react'

import { IconPullRequest, IconTerminal } from '@posthog/icons'
import { LemonButton, LemonModal, LemonSegmentedButton } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { useWizardCommand } from 'scenes/onboarding/shared/SetupWizardBanner'

import { OnboardingStepKey, type SDK } from '~/types'

import { OnboardingStep } from '../../../OnboardingStep'
import { AdblockWarning, RealtimeCheckIndicator } from '../../RealtimeCheckIndicator'
import { SDKGrid } from '../SDKGrid'
import { SDKInstructionsModal } from '../SDKInstructionsModal'
import { VariantProps } from '../types'
import { WizardCloudRunBlock } from '../WizardCloudRunBlock'
import { WizardCommandBlock } from '../WizardCommandBlock'
import { wizardInstallStepLogic } from '../wizardInstallStepLogic'
import { WizardFrameworkBadges } from '../WizardModeShell'
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
    return <WizardInstallShell takeoverActive={false} props={props} />
}

function WizardInstallStepWithSync(props: VariantProps): JSX.Element {
    // Mounts wizardProgressTrackerLogic (and its SSE) only in the sync arm.
    const takeoverActive = useWizardTakeoverActive()
    return <WizardInstallShell takeoverActive={takeoverActive} props={props} />
}

type InstallMode = 'cloud' | 'local'

/**
 * Intro + the wizard itself. It's one wizard with two ways to run it: have us run
 * it and open a PR (the primary, self-driving path), or run the CLI yourself. A
 * segmented control switches between them rather than stacking two separate
 * blocks. The cloud path only exists behind `ONBOARDING_WIZARD_CLOUD_RUN=test` on
 * cloud/dev; everywhere else this collapses to just the local command.
 */
function WizardInstallOptions({ onCloudRunQueued }: { onCloudRunQueued: () => void }): JSX.Element {
    const cloudRunEnabled = useFeatureFlag('ONBOARDING_WIZARD_CLOUD_RUN', 'test')
    const { isCloudOrDev } = useWizardCommand()
    const [mode, setMode] = useState<InstallMode>('cloud')

    const offerCloud = cloudRunEnabled && isCloudOrDev

    return (
        <>
            <WizardInstallIntro unified={offerCloud} />
            <div className="max-w-2xl mx-auto flex flex-col gap-5">
                {/* The wizard supports the same frameworks whichever way it runs, so the
                    badges live here — shared, above the mode selector — not inside a tab. */}
                {isCloudOrDev && <WizardFrameworkBadges />}
                {offerCloud && (
                    <LemonSegmentedButton
                        fullWidth
                        value={mode}
                        onChange={(value) => setMode(value)}
                        options={[
                            {
                                value: 'cloud',
                                label: 'Open a pull request',
                                icon: <IconPullRequest />,
                                'data-attr': 'wizard-install-mode-cloud',
                            },
                            {
                                value: 'local',
                                label: 'Run it yourself',
                                icon: <IconTerminal />,
                                'data-attr': 'wizard-install-mode-local',
                            },
                        ]}
                    />
                )}
                {offerCloud && mode === 'cloud' ? (
                    <WizardCloudRunBlock onQueued={onCloudRunQueued} />
                ) : (
                    <WizardCommandBlock />
                )}
            </div>
        </>
    )
}

function WizardInstallShell({ takeoverActive, props }: { takeoverActive: boolean; props: VariantProps }): JSX.Element {
    const { manualModalOpen, sdkInstructionsOpen } = useValues(wizardInstallStepLogic)
    const { setManualModalOpen, setSdkInstructionsOpen } = useActions(wizardInstallStepLogic)
    // Set once the user queues a cloud run. Lifted here (rather than read off the
    // logic) so wizardCloudRunLogic only mounts inside the flag-gated block.
    const [cloudRunQueued, setCloudRunQueued] = useState(false)
    const onCloudRunQueued = useCallback(() => setCloudRunQueued(true), [])

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

    // Once the work is handed off — the local wizard took over, or a cloud run is
    // queued — trust it: installation events aren't required to unblock Continue,
    // and Skip is redundant.
    const handedOff = takeoverActive || cloudRunQueued
    const continueDisabledReason = handedOff || installationComplete ? undefined : 'Installation is not complete'
    const showSkip = !installationComplete && !handedOff

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
                {takeoverActive ? (
                    <WizardProgressTracker />
                ) : (
                    <WizardInstallOptions onCloudRunQueued={onCloudRunQueued} />
                )}
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

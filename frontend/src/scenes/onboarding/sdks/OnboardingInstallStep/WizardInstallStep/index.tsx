import { useActions, useValues } from 'kea'

import { LemonButton, LemonModal, Link } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { OnboardingStepKey, type SDK } from '~/types'

import { wizardRunIsActive } from 'products/wizard/frontend/lib/wizardRunDisplay'
import { onboardingWizardRunLogic } from 'products/wizard/frontend/views/onboarding/onboardingWizardRunLogic'
import { WizardInstallSync } from 'products/wizard/frontend/views/onboarding/WizardInstallSync'
import { WizardOnboardingCloudRun } from 'products/wizard/frontend/views/onboarding/WizardOnboardingCloudRun'

import { OnboardingStep } from '../../../OnboardingStep'
import { useWizardCommand } from '../../../shared/useWizardCommand'
import { WizardCommandBlock } from '../../../shared/wizard-command/WizardCommandBlock'
import { WizardFrameworkIcons } from '../../../shared/wizard-command/WizardFrameworkIcons'
import { WizardFrameworkBadges, WizardModeShell } from '../../../shared/wizard-command/WizardModeShell'
import { AdblockWarning, RealtimeCheckIndicator } from '../../RealtimeCheckIndicator'
import { SDKGrid } from '../SDKGrid'
import { SDKInstructionsModal } from '../SDKInstructionsModal'
import { VariantProps, WizardOverrides } from '../types'
import { wizardInstallStepLogic } from '../wizardInstallStepLogic'
import { WizardInstallIntro } from './WizardInstallIntro'

// Onboarding's command block with the framework badges. Self-hosted gets no Wizard, so no badges either.
function OnboardingInstallOptions({
    wizardOverrides,
    compact = false,
}: {
    wizardOverrides?: WizardOverrides
    compact?: boolean
}): JSX.Element {
    const { isCloudOrDev } = useWizardCommand()
    const { cloudRunProps } = useValues(wizardInstallStepLogic)
    const { subcommand, description, supports } = wizardOverrides ?? {}
    const localBlock = (
        <WizardCommandBlock
            subcommand={subcommand}
            description={description ?? (compact ? 'Run this in your project folder. No API key needed.' : undefined)}
            hog={compact ? null : undefined}
        />
    )
    return (
        <div className="flex flex-col gap-4">
            {isCloudOrDev && (
                <div className="pb-2">
                    {supports ? (
                        <WizardFrameworkBadges items={supports} />
                    ) : compact ? (
                        <WizardFrameworkIcons />
                    ) : (
                        <WizardFrameworkBadges />
                    )}
                </div>
            )}
            {!subcommand && cloudRunProps ? (
                <WizardOnboardingCloudRun {...cloudRunProps}>{localBlock}</WizardOnboardingCloudRun>
            ) : (
                localBlock
            )}
        </div>
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
 */
export function WizardInstallStep(props: VariantProps): JSX.Element {
    const { setManualModalOpen } = useActions(wizardInstallStepLogic)
    const { currentTeam } = useValues(teamLogic)
    const { user } = useValues(userLogic)
    const projectId = !props.wizardOverrides?.subcommand && currentTeam?.id ? String(currentTeam.id) : null
    const { run } = useValues(onboardingWizardRunLogic({ projectId: projectId ?? '', userId: user?.id ?? 0 }))
    const canContinue = props.installationComplete || (!!run && (wizardRunIsActive(run) || run.status === 'completed'))
    return (
        <WizardInstallShell
            fullWidth={!!run}
            continueDisabledReason={canContinue ? undefined : 'Installation is not complete'}
            showSkip={!canContinue}
            props={props}
        >
            {props.compact ? (
                <WizardInstallSync projectId={projectId}>
                    <WizardModeShell data-attr="wizard-install-compact">
                        <p className="text-muted mb-0">
                            {props.wizardOverrides?.intro ??
                                'Wizard is a setup agent. It detects your framework, installs the SDK, and adds your project token to your environment variables.'}
                        </p>
                        <OnboardingInstallOptions wizardOverrides={props.wizardOverrides} compact />
                        <Link
                            className="self-start text-sm"
                            data-attr="sdk-continue"
                            onClick={() => setManualModalOpen(true)}
                        >
                            Want to set up manually?
                        </Link>
                    </WizardModeShell>
                </WizardInstallSync>
            ) : (
                <WizardInstallSync projectId={projectId}>
                    <>
                        <WizardInstallIntro description={props.wizardOverrides?.intro} />
                        <div className="max-w-xl mx-auto">
                            <OnboardingInstallOptions wizardOverrides={props.wizardOverrides} />
                        </div>
                        <div>
                            <LemonButton
                                type="tertiary"
                                size="small"
                                data-attr="sdk-continue"
                                onClick={() => setManualModalOpen(true)}
                            >
                                Need to set up manually?
                            </LemonButton>
                        </div>
                    </>
                </WizardInstallSync>
            )}
        </WizardInstallShell>
    )
}

function WizardInstallShell({
    children,
    fullWidth,
    continueDisabledReason,
    showSkip,
    props,
}: {
    children: React.ReactNode
    fullWidth: boolean
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
            fullWidth={fullWidth}
            title={props.installTitle}
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
            <div className="mt-6 space-y-8">{children}</div>

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

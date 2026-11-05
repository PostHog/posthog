import { useActions, useValues } from 'kea'

import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { OnboardingStepKey, type SDK } from '~/types'

import { wizardRunIsActive } from 'products/wizard/frontend/lib/wizardRunDisplay'
import { onboardingWizardRunLogic } from 'products/wizard/frontend/views/onboarding/onboardingWizardRunLogic'
import { WizardInstallSync } from 'products/wizard/frontend/views/onboarding/WizardInstallSync'
import { WizardOnboardingCloudRun } from 'products/wizard/frontend/views/onboarding/WizardOnboardingCloudRun'

import { useWizardCommand } from '../../../../../../../lib/onboarding/useWizardCommand'
import { WizardCommandBlock } from '../../../../../../../lib/onboarding/wizard-command/WizardCommandBlock'
import { WizardFrameworkBadges } from '../../../../../../../lib/onboarding/wizard-command/WizardModeShell'
import { OnboardingStep } from '../../../OnboardingStep'
import { AdblockWarning, RealtimeCheckIndicator } from '../../RealtimeCheckIndicator'
import { SDKGrid } from '../SDKGrid'
import { SDKInstructionsModal } from '../SDKInstructionsModal'
import { VariantProps, WizardOverrides } from '../types'
import { wizardInstallStepLogic } from '../wizardInstallStepLogic'
import { WizardInstallIntro } from './WizardInstallIntro'

// Onboarding's command block with the framework badges. Self-hosted gets no Wizard, so no badges either.
function OnboardingInstallOptions({ wizardOverrides }: { wizardOverrides?: WizardOverrides }): JSX.Element {
    const { isCloudOrDev } = useWizardCommand()
    const { cloudRunProps } = useValues(wizardInstallStepLogic)
    const { subcommand, description, supports } = wizardOverrides ?? {}
    const localBlock = <WizardCommandBlock subcommand={subcommand} description={description} />
    return (
        <div className="flex flex-col gap-4">
            {isCloudOrDev && (
                <div className="pb-2">
                    <WizardFrameworkBadges items={supports} />
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

import { useState } from 'react'

import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { OnboardingStepKey, type SDK } from '~/types'

import { OnboardingStep } from '../../../OnboardingStep'
import { AdblockWarning, RealtimeCheckIndicator } from '../../RealtimeCheckIndicator'
import { SDKGrid } from '../SDKGrid'
import { SDKInstructionsModal } from '../SDKInstructionsModal'
import { VariantProps } from '../types'
import { WizardCommandBlock } from '../WizardCommandBlock'
import { WizardOnlyIntro } from './WizardOnlyIntro'

/**
 * ONBOARDING_WIZARD_PROMINENCE = "wizard-only"
 * Wizard is the centered focus; the SDK grid is hidden behind a "Need to set up
 * manually?" link that opens it in a modal.
 *
 * Unlike the other variants, this one owns its own SDKInstructionsModal because it
 * needs a nested modal flow: picking an SDK in the manual-setup modal closes that
 * modal and opens the instructions modal; closing the instructions modal re-opens the
 * manual-setup modal (back-button behavior). That coordination can't live in the
 * parent, so the shared modal in index.tsx is skipped for this variant.
 *
 * Nested experiment (ONBOARDING_WIZARD_INSTALLATION_IMPROVED_COPY, #team-growth):
 *   WizardOnlyIntro dispatches between control and test copy internally. The
 *   variant stays agnostic — it just renders the intro and the shared
 *   WizardCommandBlock; the intro file handles the copy swap.
 */
export function WizardOnlyVariant({
    sdkGridProps,
    sdkInstructionMap,
    adblockResult,
    installationComplete,
    listeningForName,
    teamPropertyToVerify,
    selectedSDK,
    header,
}: VariantProps): JSX.Element {
    const [manualModalOpen, setManualModalOpen] = useState(false)
    const [sdkInstructionsOpen, setSdkInstructionsOpen] = useState(false)

    const handleWizardOnlySDKClick = (sdk: SDK): void => {
        sdkGridProps.onSDKClick(sdk)
        setManualModalOpen(false)
        setSdkInstructionsOpen(true)
    }

    return (
        <OnboardingStep
            title="Install"
            stepKey={OnboardingStepKey.INSTALL}
            continueDisabledReason={!installationComplete ? 'Installation is not complete' : undefined}
            showSkip={!installationComplete}
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
                <WizardOnlyIntro />

                <div className="max-w-xl mx-auto">
                    <WizardCommandBlock />
                </div>

                <div className="text-center">
                    <LemonButton type="tertiary" size="small" onClick={() => setManualModalOpen(true)}>
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
                    <SDKGrid {...{ ...sdkGridProps, onSDKClick: handleWizardOnlySDKClick }} showTopControls />
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

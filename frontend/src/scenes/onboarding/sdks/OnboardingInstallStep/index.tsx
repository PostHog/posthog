import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { teamLogic } from 'scenes/teamLogic'

import { OnboardingStepKey, type SDK, SDKInstructionsMap, SDKTagOverrides } from '~/types'

import { OnboardingStepComponentType } from '../../onboardingLogic'
import { OnboardingStep } from '../../OnboardingStep'
import { useAdblockDetection } from '../hooks/useAdblockDetection'
import { useInstallationComplete } from '../hooks/useInstallationComplete'
import { AdblockWarning, RealtimeCheckIndicator } from '../RealtimeCheckIndicator'
import { sdksLogic } from '../sdksLogic'
import { SDKGrid } from './SDKGrid'
import { SDKInstructionsModal } from './SDKInstructionsModal'
import { SDKGridProps, VariantProps } from './types'
import { WizardHeroVariant } from './variants/WizardHeroVariant'
import { WizardOnlyVariant } from './variants/WizardOnlyVariant'
import { WizardTabVariant } from './variants/WizardTabVariant'

interface OnboardingInstallStepProps {
    sdkInstructionMap: SDKInstructionsMap
    sdkTagOverrides?: SDKTagOverrides
    listeningForName?: string
    teamPropertyToVerify?: string
    header?: React.ReactNode
}

/**
 * Onboarding install step — renders the "Install" screen during onboarding.
 *
 * Layout is driven by two growth experiments:
 *
 *   ONBOARDING_WIZARD_PROMINENCE (#team-growth)
 *     control     — SDK grid only (legacy baseline)
 *     wizard-hero — wizard banner prominently above the SDK grid
 *     wizard-tab  — wizard and SDK grid split across two tabs
 *     wizard-only — wizard centered; SDK grid hidden behind a "manual setup" link
 *
 *   ONBOARDING_SKIP_INSTALL_STEP (#team-growth)
 *     Moves the "Skip installation" button to the bottom of the step. Ignored by
 *     wizard variants — those manage their own skip UI via OnboardingStep.showSkip.
 *
 * Per-variant implementations live in ./variants. WizardOnlyVariant renders its own
 * SDKInstructionsModal (it needs a nested modal flow: manual-setup → SDK instructions
 * → back to manual-setup), so the shared `instructionsModal` below is not rendered
 * for it.
 */
export const OnboardingInstallStep: OnboardingStepComponentType<OnboardingInstallStepProps> = ({
    sdkInstructionMap,
    sdkTagOverrides,
    listeningForName = 'event',
    teamPropertyToVerify = 'ingested_event',
    header,
}) => {
    const { setAvailableSDKInstructionsMap, setSDKTagOverrides, selectSDK, setSearchTerm, setSelectedTag } =
        useActions(sdksLogic)
    const { filteredSDKs, selectedSDK, tags, searchTerm, selectedTag } = useValues(sdksLogic)
    const [instructionsModalOpen, setInstructionsModalOpen] = useState(false)
    const { currentTeam } = useValues(teamLogic)

    const installationComplete = useInstallationComplete(teamPropertyToVerify)
    const adblockResult = useAdblockDetection()
    const isSkipButtonExperiment = useFeatureFlag('ONBOARDING_SKIP_INSTALL_STEP', 'test')

    const isWizardHero = useFeatureFlag('ONBOARDING_WIZARD_PROMINENCE', 'wizard-hero')
    const isWizardTab = useFeatureFlag('ONBOARDING_WIZARD_PROMINENCE', 'wizard-tab')
    const isWizardOnly = useFeatureFlag('ONBOARDING_WIZARD_PROMINENCE', 'wizard-only')

    useEffect(() => {
        setSDKTagOverrides(sdkTagOverrides ?? {})
        setAvailableSDKInstructionsMap(sdkInstructionMap)
    }, [sdkInstructionMap, sdkTagOverrides, setAvailableSDKInstructionsMap, setSDKTagOverrides])

    const showSkipAtBottom = isSkipButtonExperiment && !installationComplete
    const showTopSkipButton = !isSkipButtonExperiment || installationComplete

    const handleSDKClick = (sdk: SDK): void => {
        selectSDK(sdk)
        setInstructionsModalOpen(true)
    }

    const isWizardVariant = isWizardHero || isWizardTab || isWizardOnly

    const sdkGridProps: SDKGridProps = {
        filteredSDKs: filteredSDKs ?? [],
        searchTerm,
        selectedTag,
        tags,
        onSDKClick: handleSDKClick,
        onSearchChange: setSearchTerm,
        onTagChange: setSelectedTag,
        currentTeam,
        showTopControls: true,
        installationComplete,
        // Wizard variants rely on OnboardingStep.showSkip for the skip/continue button,
        // so we suppress SDKGrid's duplicate top-right NextButton to avoid rendering two.
        showTopSkipButton: isWizardVariant ? false : showTopSkipButton,
    }

    const variantProps: VariantProps = {
        sdkGridProps,
        sdkInstructionMap,
        adblockResult,
        installationComplete,
        listeningForName,
        teamPropertyToVerify,
        selectedSDK,
        header,
    }

    const instructionsModal = selectedSDK && (
        <SDKInstructionsModal
            isOpen={instructionsModalOpen}
            onClose={() => setInstructionsModalOpen(false)}
            sdk={selectedSDK}
            sdkInstructionMap={sdkInstructionMap}
            adblockResult={adblockResult}
            verifyingProperty={teamPropertyToVerify}
            verifyingName={listeningForName}
        />
    )

    // Route to the appropriate experiment variant. WizardOnlyVariant renders its own SDKInstructionsModal.
    if (isWizardHero) {
        return (
            <>
                <WizardHeroVariant {...variantProps} />
                {instructionsModal}
            </>
        )
    }

    if (isWizardTab) {
        return (
            <>
                <WizardTabVariant {...variantProps} />
                {instructionsModal}
            </>
        )
    }

    if (isWizardOnly) {
        return <WizardOnlyVariant {...variantProps} />
    }

    // Control: existing behavior — SDK grid without the wizard hero
    return (
        <OnboardingStep
            title="Install"
            stepKey={OnboardingStepKey.INSTALL}
            continueDisabledReason={!installationComplete ? 'Installation is not complete' : undefined}
            showSkip={showSkipAtBottom}
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
            <div className="mt-6">
                <SDKGrid {...sdkGridProps} />
            </div>
            {instructionsModal}
        </OnboardingStep>
    )
}

OnboardingInstallStep.stepKey = OnboardingStepKey.INSTALL

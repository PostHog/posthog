import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect, useRef, useState } from 'react'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { isMobile } from 'lib/utils'
import { teamLogic } from 'scenes/teamLogic'

import { ProductKey } from '~/queries/schema/schema-general'
import { OnboardingStepKey, type SDK, SDKInstructionsMap, SDKTagOverrides } from '~/types'

import { onboardingLogic, OnboardingStepComponentType } from '../../onboardingLogic'
import { OnboardingStep } from '../../OnboardingStep'
import { availableOnboardingProducts } from '../../utils'
import { useAdblockDetection } from '../hooks/useAdblockDetection'
import { useInstallationComplete } from '../hooks/useInstallationComplete'
import { AdblockWarning, RealtimeCheckIndicator } from '../RealtimeCheckIndicator'
import { sdksLogic } from '../sdksLogic'
import { MobileInstallHandoff } from './MobileInstallHandoff'
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
    /** When true, the realtime check indicator is hidden and Continue is always enabled. */
    hideInstallationCheck?: boolean
    header?: React.ReactNode
}

/**
 * Onboarding install step — renders the "Install" screen during onboarding.
 *
 * Layout is driven by three growth experiments:
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
 *   ONBOARDING_MOBILE_INSTALL_HELPER (#team-growth)
 *     When the user is on a mobile device (navigator.userAgent check) AND in the
 *     `test` arm, replaces the entire variant dispatch with MobileInstallHandoff,
 *     a screen that offers to share the install URL to the user's computer via
 *     the Web Share API. Users can dismiss it with "continue here anyway" which
 *     falls through to the regular variant dispatch. See the data-driven rationale
 *     in that component's JSDoc.
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
    hideInstallationCheck = false,
    header,
}) => {
    const { setAvailableSDKInstructionsMap, setSDKTagOverrides, selectSDK, setSearchTerm, setSelectedTag } =
        useActions(sdksLogic)
    const { filteredSDKs, selectedSDK, tags, searchTerm, selectedTag } = useValues(sdksLogic)
    const [instructionsModalOpen, setInstructionsModalOpen] = useState(false)
    const [mobileHandoffDismissed, setMobileHandoffDismissed] = useState(false)
    const linkOpenedCapturedRef = useRef(false)
    const { currentTeam } = useValues(teamLogic)
    const { productKey } = useValues(onboardingLogic)
    const productName = productKey
        ? availableOnboardingProducts[productKey as keyof typeof availableOnboardingProducts]?.name
        : undefined
    const installTitle = productName ? `Install ${productName}` : 'Install your SDK'

    const installationCompleteFromTeam = useInstallationComplete(teamPropertyToVerify)
    const installationComplete = hideInstallationCheck || installationCompleteFromTeam
    const adblockResult = useAdblockDetection()
    const isSkipButtonExperiment = useFeatureFlag('ONBOARDING_SKIP_INSTALL_STEP', 'test')

    const isWizardHero = useFeatureFlag('ONBOARDING_WIZARD_PROMINENCE', 'wizard-hero')
    const isWizardTab = useFeatureFlag('ONBOARDING_WIZARD_PROMINENCE', 'wizard-tab')
    const isWizardOnly = useFeatureFlag('ONBOARDING_WIZARD_PROMINENCE', 'wizard-only')

    // Logs uses OpenTelemetry, not the PostHog JS wizard. When the Logs install step is
    // shown (either directly or after diversion from another product's wizard step),
    // skip all wizard variants and fall through to the control SDK-grid layout.
    const isLogsProduct = productKey === ProductKey.LOGS

    // Double-gated: both the feature flag AND the client-side mobile check must
    // be true. The flag controls experiment enrollment (targeted to mobile
    // devices at the flag definition level in PostHog); isMobile() is the hard
    // guarantee that the mobile-specific UI NEVER appears on desktop, even if
    // a desktop user somehow ends up in the `test` arm.
    const isMobileHandoffTest = useFeatureFlag('ONBOARDING_MOBILE_INSTALL_HELPER', 'test')
    const showMobileHandoff = isMobileHandoffTest && isMobile() && !mobileHandoffDismissed

    useEffect(() => {
        setSDKTagOverrides(sdkTagOverrides ?? {})
        setAvailableSDKInstructionsMap(sdkInstructionMap)
    }, [sdkInstructionMap, sdkTagOverrides, setAvailableSDKInstructionsMap, setSDKTagOverrides])

    // Closes the experiment funnel: desktop lands here from a shared link
    // carrying `?handoff=mobile`. Fires exactly once per mount via a ref
    // guard (useEffect deps are empty so it would re-run on StrictMode
    // double-invoke otherwise), then strips the query param from the URL
    // so refreshes / back-and-forth navigation don't re-capture.
    useEffect(() => {
        if (linkOpenedCapturedRef.current) {
            return
        }
        const params = new URLSearchParams(window.location.search)
        if (params.get('handoff') !== 'mobile') {
            return
        }
        linkOpenedCapturedRef.current = true
        posthog.capture('mobile install handoff link opened')
        params.delete('handoff')
        params.delete('step')
        const newSearch = params.toString()
        const newUrl = window.location.pathname + (newSearch ? `?${newSearch}` : '') + window.location.hash
        window.history.replaceState(null, '', newUrl)
    }, [])

    const showSkipAtBottom = isSkipButtonExperiment && !installationComplete
    const showTopSkipButton = !isSkipButtonExperiment || installationComplete

    const handleSDKClick = (sdk: SDK): void => {
        selectSDK(sdk)
        setInstructionsModalOpen(true)
    }

    const isWizardVariant = (isWizardHero || isWizardTab || isWizardOnly) && !isLogsProduct

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
            hideInstallationCheck={hideInstallationCheck}
        />
    )

    // Mobile users in the test arm get the handoff screen instead of the regular
    // variant dispatch. "Continue on this device" dismisses and falls through below.
    // Logs onboarding uses OpenTelemetry, which has no `ingested_event` signal — the
    // mobile handoff would render a RealtimeCheckIndicator that never resolves and
    // leave Continue disabled forever, so we skip the handoff for Logs entirely.
    if (showMobileHandoff && !isLogsProduct) {
        return (
            <MobileInstallHandoff
                listeningForName={listeningForName}
                teamPropertyToVerify={teamPropertyToVerify}
                installationComplete={installationComplete}
                header={header}
                onContinueHere={() => setMobileHandoffDismissed(true)}
            />
        )
    }

    // Route to the appropriate experiment variant. WizardOnlyVariant renders its own SDKInstructionsModal.
    if (isWizardHero && !isLogsProduct) {
        return (
            <>
                <WizardHeroVariant {...variantProps} />
                {instructionsModal}
            </>
        )
    }

    if (isWizardTab && !isLogsProduct) {
        return (
            <>
                <WizardTabVariant {...variantProps} />
                {instructionsModal}
            </>
        )
    }

    if (isWizardOnly && !isLogsProduct) {
        return <WizardOnlyVariant {...variantProps} />
    }

    // Control: existing behavior — SDK grid without the wizard hero
    return (
        <OnboardingStep
            title={installTitle}
            stepKey={OnboardingStepKey.INSTALL}
            continueDisabledReason={!installationComplete ? 'Installation is not complete' : undefined}
            showSkip={showSkipAtBottom}
            actions={
                hideInstallationCheck ? undefined : (
                    <div className="pr-2">
                        <RealtimeCheckIndicator
                            teamPropertyToVerify={teamPropertyToVerify}
                            listeningForName={listeningForName}
                        />
                    </div>
                )
            }
        >
            {header}
            {!hideInstallationCheck && !installationComplete && <AdblockWarning adblockResult={adblockResult} />}
            <div className="mt-6">
                <SDKGrid {...sdkGridProps} />
            </div>
            {instructionsModal}
        </OnboardingStep>
    )
}

OnboardingInstallStep.stepKey = OnboardingStepKey.INSTALL

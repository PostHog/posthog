import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect, useRef, useState } from 'react'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { isMobile } from 'lib/utils/dom'
import { availableOnboardingProducts } from 'scenes/onboarding/shared/utils'
import { teamLogic } from 'scenes/teamLogic'

import { ProductKey } from '~/queries/schema/schema-general'
import { OnboardingStepKey, type SDK, SDKInstructionsMap, SDKTagOverrides } from '~/types'

import { onboardingLogic, OnboardingStepComponentType } from '../../onboardingLogic'
import { OnboardingStep } from '../../OnboardingStep'
import { INSTALL_DEDUP_KEYS } from '../../types'
import { useAdblockDetection } from '../hooks/useAdblockDetection'
import { useInstallationComplete } from '../hooks/useInstallationComplete'
import { AdblockWarning, RealtimeCheckIndicator } from '../RealtimeCheckIndicator'
import { sdksLogic } from '../sdksLogic'
import { MobileInstallHandoff } from './MobileInstallHandoff'
import { SDKGrid } from './SDKGrid'
import { SDKInstructionsModal } from './SDKInstructionsModal'
import { SDKGridProps, VariantProps } from './types'
import { WizardInstallStep } from './WizardInstallStep'

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
 * Onboarding install step — wizard-centered layout for non-Logs products, bare
 * SDK grid for Logs (which uses OpenTelemetry, not the PostHog JS wizard).
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
    const { currentStepProductKey, currentFlowStep } = useValues(onboardingLogic)
    const productName = currentStepProductKey
        ? availableOnboardingProducts[currentStepProductKey as keyof typeof availableOnboardingProducts]?.name
        : undefined
    // The shared posthog-js step gets a generic "Install" title — naming it after
    // the dedup-survivor product would mislead users installing several at once.
    const isSdkInstallStep = currentFlowStep?.dedupKey === INSTALL_DEDUP_KEYS.POSTHOG_JS
    const installTitle = isSdkInstallStep ? 'Install' : productName ? `Install ${productName}` : 'Install your SDK'

    const installationCompleteFromTeam = useInstallationComplete(teamPropertyToVerify)
    const installationComplete = hideInstallationCheck || installationCompleteFromTeam
    const adblockResult = useAdblockDetection()

    const isLogsProduct = currentStepProductKey === ProductKey.LOGS

    // Both gates required: the flag controls enrollment (targeted in PostHog),
    // isMobile() is the hard guarantee the mobile UI never appears on desktop.
    const isMobileHandoffTest = useFeatureFlag('ONBOARDING_MOBILE_INSTALL_HELPER', 'test')
    const showMobileHandoff = isMobileHandoffTest && isMobile() && !mobileHandoffDismissed

    useEffect(() => {
        setSDKTagOverrides(sdkTagOverrides ?? {})
        setAvailableSDKInstructionsMap(sdkInstructionMap)
    }, [sdkInstructionMap, sdkTagOverrides, setAvailableSDKInstructionsMap, setSDKTagOverrides])

    // Captures the funnel-close event when desktop arrives via a `?handoff=mobile`
    // share link, then strips the param so refreshes / back-nav don't re-capture.
    // The ref guard is required because StrictMode double-invokes effects in dev.
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

    const showSkipAtBottom = !installationComplete
    const showTopSkipButton = installationComplete

    const handleSDKClick = (sdk: SDK): void => {
        selectSDK(sdk)
        setInstructionsModalOpen(true)
    }

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
        // The wizard variant uses OnboardingStep.showSkip; suppress SDKGrid's
        // duplicate top-right button to avoid two next-buttons. Only Logs renders
        // the bare grid as a primary surface, so it keeps the top button.
        showTopSkipButton: isLogsProduct ? showTopSkipButton : false,
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

    // Non-Logs products get the wizard-centered layout, which owns its own SDKInstructionsModal.
    if (!isLogsProduct) {
        return <WizardInstallStep {...variantProps} />
    }

    // Logs: bare SDK grid — OpenTelemetry, not the PostHog JS wizard.
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

import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect, useRef, useState } from 'react'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { isMobile } from 'lib/utils/dom'
import { humanList } from 'lib/utils/strings'
import { availableOnboardingProducts } from 'scenes/onboarding/shared/utils'
import { teamLogic } from 'scenes/teamLogic'

import { ProductKey } from '~/queries/schema/schema-general'
import { OnboardingStepKey, type SDK, SDKDocsLinkOverrides, SDKInstructionsMap, SDKTagOverrides } from '~/types'

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
import { SDKGridProps, VariantProps, WizardOverrides } from './types'
import { WizardInstallStep } from './WizardInstallStep'

interface OnboardingInstallStepProps {
    sdkInstructionMap: SDKInstructionsMap
    sdkDocsLinkOverrides?: SDKDocsLinkOverrides
    sdkTagOverrides?: SDKTagOverrides
    listeningForName?: string
    teamPropertyToVerify?: string
    /** When true, the realtime check indicator is hidden and Continue is always enabled. */
    hideInstallationCheck?: boolean
    header?: React.ReactNode
    wizardOverrides?: WizardOverrides
}

/**
 * Onboarding install step — wizard-centered layout for non-Logs products, bare
 * SDK grid for Logs (which uses OpenTelemetry, not the PostHog JS wizard).
 */
export const OnboardingInstallStep: OnboardingStepComponentType<OnboardingInstallStepProps> = ({
    sdkInstructionMap,
    sdkDocsLinkOverrides,
    sdkTagOverrides,
    listeningForName = 'event',
    teamPropertyToVerify = 'ingested_event',
    hideInstallationCheck = false,
    header,
    wizardOverrides,
}) => {
    const {
        setAvailableSDKInstructionsMap,
        setSDKDocsLinkOverrides,
        setSDKTagOverrides,
        selectSDK,
        setSearchTerm,
        setSelectedTag,
    } = useActions(sdksLogic)
    const { filteredSDKs, selectedSDK, tags, searchTerm, selectedTag } = useValues(sdksLogic)
    const [instructionsModalOpen, setInstructionsModalOpen] = useState(false)
    const [mobileHandoffDismissed, setMobileHandoffDismissed] = useState(false)
    const linkOpenedCapturedRef = useRef(false)
    const { currentTeam } = useValues(teamLogic)
    const { currentStepProductKey, currentFlowStep, flow } = useValues(onboardingLogic)
    const productName = currentStepProductKey
        ? availableOnboardingProducts[currentStepProductKey as keyof typeof availableOnboardingProducts]?.name
        : undefined
    const isSdkInstallStep = currentFlowStep?.dedupKey === INSTALL_DEDUP_KEYS.POSTHOG_JS
    // With several install steps in one flow, a bare "Install" reads as a duplicate, so the shared
    // posthog-js step is titled after its dedup survivor; the subtitle names the full covered set.
    const installStepCount = flow.filter((step) => step.stepKey === OnboardingStepKey.INSTALL).length
    const installTitle =
        isSdkInstallStep && installStepCount <= 1
            ? 'Install'
            : productName
              ? `Install ${productName}`
              : 'Install your SDK'
    // The dedup record is what this step actually covers; other products keep their own install step.
    const coveredNames = (currentFlowStep?.additionalProductKeys ?? [currentStepProductKey])
        .map((key) => availableOnboardingProducts[key as keyof typeof availableOnboardingProducts]?.name)
        .filter((name): name is string => !!name)
    const installSubtitle =
        isSdkInstallStep && coveredNames.length > 1 ? `One install covers ${humanList(coveredNames)}.` : undefined

    const installationCompleteFromTeam = useInstallationComplete(teamPropertyToVerify)
    const installationComplete = hideInstallationCheck || installationCompleteFromTeam
    const adblockResult = useAdblockDetection()

    const isLogsProduct = currentStepProductKey === ProductKey.LOGS

    // Both gates required: the flag controls enrollment (targeted in PostHog),
    // isMobile() is the hard guarantee the mobile UI never appears on desktop.
    const isMobileHandoffTest = useFeatureFlag('ONBOARDING_MOBILE_INSTALL_HELPER', 'test')
    const showMobileHandoff = isMobileHandoffTest && isMobile() && !mobileHandoffDismissed

    useEffect(() => {
        setSDKDocsLinkOverrides(sdkDocsLinkOverrides ?? {})
        setSDKTagOverrides(sdkTagOverrides ?? {})
        setAvailableSDKInstructionsMap(sdkInstructionMap)
    }, [
        sdkDocsLinkOverrides,
        sdkInstructionMap,
        sdkTagOverrides,
        setAvailableSDKInstructionsMap,
        setSDKDocsLinkOverrides,
        setSDKTagOverrides,
    ])

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
        wizardOverrides,
        installTitle,
        installSubtitle,
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
                    <div className="pr-2 min-w-0">
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

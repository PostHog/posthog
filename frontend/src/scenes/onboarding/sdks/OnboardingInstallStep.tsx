import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconArrowLeft, IconArrowRight, IconCopy } from '@posthog/icons'
import { LemonButton, LemonCard, LemonInput, LemonModal, LemonTabs, SpinnerOverlay } from '@posthog/lemon-ui'

import { InviteMembersButton } from 'lib/components/Account/InviteMembersButton'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { teamLogic } from 'scenes/teamLogic'

import { ProductKey } from '~/queries/schema/schema-general'
import { OnboardingStepKey, type SDK, SDKInstructionsMap, SDKTag } from '~/types'

import { OnboardingStep } from '../OnboardingStep'
import { onboardingLogic } from '../onboardingLogic'
import { RealtimeCheckIndicator } from './RealtimeCheckIndicator'
import { SDKSnippet } from './SDKSnippet'
import { useInstallationComplete } from './hooks/useInstallationComplete'
import { sdksLogic } from './sdksLogic'

export function SDKInstructionsModal({
    isOpen,
    onClose,
    sdk,
    sdkInstructionMap,
    productKey,
    verifyingProperty = 'ingested_event',
    verifyingName = 'event',
}: {
    isOpen: boolean
    onClose: () => void
    sdk?: SDK
    sdkInstructionMap: SDKInstructionsMap
    productKey: ProductKey
    verifyingProperty?: string
    verifyingName?: string
}): JSX.Element {
    const installationComplete = useInstallationComplete(verifyingProperty)

    const sdkInstructions = sdkInstructionMap[sdk?.key as keyof typeof sdkInstructionMap] as
        | (() => JSX.Element)
        | undefined

    return (
        <LemonModal isOpen={isOpen} onClose={onClose} simple title="">
            {!sdk?.key || !sdkInstructions ? (
                <SpinnerOverlay />
            ) : (
                <div className="flex flex-col h-full">
                    <header className="p-4 flex items-center gap-2">
                        <LemonButton icon={<IconArrowLeft />} onClick={onClose} size="xsmall">
                            All SDKs
                        </LemonButton>
                    </header>
                    <div className="flex-grow overflow-y-auto px-4 py-2">
                        <SDKSnippet sdk={sdk} sdkInstructions={sdkInstructions} productKey={productKey} />
                    </div>
                    <footer className="sticky bottom-0 w-full bg-bg-light dark:bg-bg-depth rounded-b-sm p-2 flex justify-between items-center gap-2 px-4">
                        <RealtimeCheckIndicator
                            teamPropertyToVerify={verifyingProperty}
                            listeningForName={verifyingName}
                        />
                        <NextButton installationComplete={installationComplete} />
                    </footer>
                </div>
            )}
        </LemonModal>
    )
}

export type SDKsProps = {
    sdkInstructionMap: SDKInstructionsMap
    productKey: ProductKey
    stepKey?: OnboardingStepKey
    listeningForName?: string
    teamPropertyToVerify?: string
}

export function OnboardingInstallStep({
    sdkInstructionMap,
    productKey,
    stepKey = OnboardingStepKey.INSTALL,
    listeningForName = 'event',
    teamPropertyToVerify = 'ingested_event',
}: SDKsProps): JSX.Element {
    const { setAvailableSDKInstructionsMap, selectSDK, setSearchTerm, setSelectedTag } = useActions(sdksLogic)
    const { filteredSDKs, selectedSDK, tags, searchTerm, selectedTag } = useValues(sdksLogic)
    const [instructionsModalOpen, setInstructionsModalOpen] = useState(false)
    const { currentTeam } = useValues(teamLogic)

    const installationComplete = useInstallationComplete(teamPropertyToVerify)
    const isSkipButtonExperiment = useFeatureFlag('ONBOARDING_SKIP_INSTALL_STEP', 'test')

    useEffect(() => {
        setAvailableSDKInstructionsMap(sdkInstructionMap)
    }, [sdkInstructionMap, setAvailableSDKInstructionsMap])

    // In the experiment, show skip at bottom only when installation is NOT complete
    const showSkipAtBottom = isSkipButtonExperiment && !installationComplete
    // In the experiment, hide the top skip button (but still show Continue when installation is complete)
    const showTopSkipButton = !isSkipButtonExperiment || installationComplete

    return (
        <OnboardingStep
            title="Install"
            stepKey={stepKey}
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
            <div className="flex flex-col gap-y-4 mt-6">
                <div className="flex flex-col gap-y-2">
                    <div className="flex flex-col-reverse md:flex-row justify-between gap-4">
                        <LemonInput
                            value={searchTerm}
                            onChange={setSearchTerm}
                            placeholder="Search"
                            className="w-full max-w-[220px]"
                        />
                        <div className="flex flex-row flex-wrap gap-2">
                            <LemonButton
                                size="small"
                                type="primary"
                                onClick={() => void copyToClipboard(currentTeam?.api_token || '', 'Project API key')}
                                icon={<IconCopy />}
                                data-attr="copy-api-key"
                            >
                                Copy API key
                            </LemonButton>
                            <InviteMembersButton
                                type="primary"
                                size="small"
                                fullWidth={false}
                                text="Invite developer"
                            />
                            {showTopSkipButton && (
                                <NextButton size="small" installationComplete={installationComplete} />
                            )}
                        </div>
                    </div>
                    <LemonTabs
                        activeKey={selectedTag ?? 'All'}
                        onChange={(key) => setSelectedTag(key === 'All' ? null : (key as SDKTag))}
                        tabs={tags.map((tag) => ({
                            key: tag,
                            label: tag,
                        }))}
                    />
                    <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
                        {(filteredSDKs ?? []).map((sdk) => (
                            <LemonCard
                                key={sdk.key}
                                className="p-4 cursor-pointer flex flex-col items-start justify-center"
                                onClick={() => {
                                    selectSDK(sdk)
                                    setInstructionsModalOpen(true)
                                }}
                            >
                                <div className="w-8 h-8 mb-2">
                                    {typeof sdk.image === 'string' ? (
                                        <img src={sdk.image} className="w-8 h-8" alt={`${sdk.name} logo`} />
                                    ) : typeof sdk.image === 'object' && 'default' in sdk.image ? (
                                        <img src={sdk.image.default} className="w-8 h-8" alt={`${sdk.name} logo`} />
                                    ) : (
                                        sdk.image
                                    )}
                                </div>

                                <strong>{sdk.name}</strong>
                            </LemonCard>
                        ))}

                        {/* This will open a survey to collect feedback on the SDKs we don't support yet */}
                        {/* https://us.posthog.com/project/2/surveys/019b47ab-5f19-0000-7f31-4f9681cde589 */}
                        {searchTerm && (
                            <LemonCard className="p-4 cursor-pointer flex flex-col items-start justify-center col-span-1 sm:col-span-2">
                                <div className="flex flex-col items-start gap-2">
                                    <span className="mb-2 text-muted">
                                        Don&apos;t see your SDK listed? We are always looking to expand our list of
                                        supported SDKs.
                                    </span>
                                    <LemonButton
                                        data-attr="onboarding-reach-out-to-us-button"
                                        type="secondary"
                                        size="small"
                                        targetBlank
                                    >
                                        Reach out to us
                                    </LemonButton>
                                </div>
                            </LemonCard>
                        )}
                    </div>
                </div>
            </div>

            {selectedSDK && (
                <SDKInstructionsModal
                    isOpen={instructionsModalOpen}
                    onClose={() => setInstructionsModalOpen(false)}
                    sdk={selectedSDK}
                    sdkInstructionMap={sdkInstructionMap}
                    productKey={productKey}
                    verifyingProperty={teamPropertyToVerify}
                    verifyingName={listeningForName}
                />
            )}
        </OnboardingStep>
    )
}

interface NextButtonProps {
    installationComplete: boolean
    size?: 'small' | 'medium'
}

const NextButton = ({ installationComplete, size = 'medium' }: NextButtonProps): JSX.Element => {
    const { hasNextStep } = useValues(onboardingLogic)
    const { completeOnboarding, goToNextStep } = useActions(onboardingLogic)
    const { reportOnboardingStepCompleted, reportOnboardingStepSkipped } = useActions(eventUsageLogic)

    const advance = !hasNextStep ? completeOnboarding : goToNextStep
    const skipInstallation = (): void => {
        reportOnboardingStepSkipped(OnboardingStepKey.INSTALL)
        advance()
    }

    const continueInstallation = (): void => {
        reportOnboardingStepCompleted(OnboardingStepKey.INSTALL)
        advance()
    }

    if (!installationComplete) {
        return (
            <LemonButton type="secondary" size={size} onClick={skipInstallation}>
                Skip installation
            </LemonButton>
        )
    }

    return (
        <LemonButton
            data-attr="sdk-continue"
            sideIcon={hasNextStep ? <IconArrowRight /> : null}
            type="primary"
            status="alt"
            onClick={continueInstallation}
        >
            Continue
        </LemonButton>
    )
}

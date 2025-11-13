import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconArrowLeft, IconArrowRight, IconChatHelp, IconCopy } from '@posthog/icons'
import { LemonButton, LemonCard, LemonInput, LemonModal, LemonTabs, SpinnerOverlay } from '@posthog/lemon-ui'

import { InviteMembersButton } from 'lib/components/Account/InviteMembersButton'
import { supportLogic } from 'lib/components/Support/supportLogic'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { teamLogic } from 'scenes/teamLogic'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { OnboardingStepKey, ProductKey, type SDK, SDKInstructionsMap, SDKTag, SidePanelTab } from '~/types'

import { OnboardingStep } from '../OnboardingStep'
import { onboardingLogic } from '../onboardingLogic'
import { RealtimeCheckIndicator } from './RealtimeCheckIndicator'
import { SDKSnippet } from './SDKSnippet'
import { useInstallationComplete } from './hooks/useInstallationComplete'
import { sdksLogic } from './sdksLogic'

export type SDKsProps = {
    sdkInstructionMap: SDKInstructionsMap
    productKey: ProductKey
    stepKey?: OnboardingStepKey
    listeningForName?: string
    teamPropertyToVerify?: string
}

const NextButton = ({
    installationComplete,
    size = 'medium',
}: {
    installationComplete: boolean
    size?: 'small' | 'medium'
}): JSX.Element => {
    const { hasNextStep } = useValues(onboardingLogic)
    const { completeOnboarding, goToNextStep } = useActions(onboardingLogic)

    if (!installationComplete) {
        return (
            <LemonButton
                type="secondary"
                size={size}
                onClick={() => (!hasNextStep ? completeOnboarding() : goToNextStep())}
            >
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
            onClick={() => (!hasNextStep ? completeOnboarding() : goToNextStep())}
        >
            Continue
        </LemonButton>
    )
}

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
    const { closeSidePanel } = useActions(sidePanelStateLogic)
    const { selectedTab, sidePanelOpen } = useValues(sidePanelStateLogic)
    const { openSupportForm } = useActions(supportLogic)
    const { isCloudOrDev } = useValues(preflightLogic)
    const { currentTeam } = useValues(teamLogic)
    const supportFormInOnboarding = useFeatureFlag('SUPPORT_FORM_IN_ONBOARDING')

    const installationComplete = useInstallationComplete(teamPropertyToVerify)

    useEffect(() => {
        setAvailableSDKInstructionsMap(sdkInstructionMap)
    }, [sdkInstructionMap, setAvailableSDKInstructionsMap])

    return (
        <OnboardingStep
            title="Install"
            stepKey={stepKey}
            continueOverride={<NextButton installationComplete={installationComplete} />}
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
                            {isCloudOrDev && supportFormInOnboarding && (
                                <LemonButton
                                    size="small"
                                    type="primary"
                                    icon={<IconChatHelp />}
                                    onClick={() =>
                                        selectedTab === SidePanelTab.Support && sidePanelOpen
                                            ? closeSidePanel()
                                            : openSupportForm({
                                                  kind: 'support',
                                                  target_area: 'onboarding',
                                                  isEmailFormOpen: true,
                                                  severity_level: 'low',
                                              })
                                    }
                                >
                                    Get help
                                </LemonButton>
                            )}
                            <NextButton size="small" installationComplete={installationComplete} />
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
                                {typeof sdk.image === 'string' ? (
                                    <img src={sdk.image} className="w-8 h-8 mb-2" alt={`${sdk.name} logo`} />
                                ) : typeof sdk.image === 'object' && 'default' in sdk.image ? (
                                    <img src={sdk.image.default} className="w-8 h-8 mb-2" alt={`${sdk.name} logo`} />
                                ) : (
                                    sdk.image
                                )}
                                <strong>{sdk.name}</strong>
                            </LemonCard>
                        ))}
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

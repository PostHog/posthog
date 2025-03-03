import { IconArrowLeft, IconArrowRight, IconChatHelp } from '@posthog/icons'
import { LemonButton, LemonCard, LemonInput, LemonModal, LemonTabs, SpinnerOverlay } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { InviteMembersButton } from '~/layout/navigation/TopBar/AccountPopover'
import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { type SDK, SDKInstructionsMap, SDKTag, SidePanelTab } from '~/types'

import { OnboardingStepKey } from '../onboardingLogic'
import { onboardingLogic } from '../onboardingLogic'
import { OnboardingStep } from '../OnboardingStep'
import { useInstallationComplete } from './hooks/useInstallationComplete'
import { RealtimeCheckIndicator } from './RealtimeCheckIndicator'
import type { SDKsProps } from './SDKs'
import { sdksLogic } from './sdksLogic'
import { SDKSnippet } from './SDKSnippet'

const NextButton = ({ installationComplete }: { installationComplete: boolean }): JSX.Element => {
    const { hasNextStep } = useValues(onboardingLogic)
    const { completeOnboarding, goToNextStep } = useActions(onboardingLogic)

    if (!installationComplete) {
        return (
            <LemonButton type="secondary" onClick={() => (!hasNextStep ? completeOnboarding() : goToNextStep())}>
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
    verifyingProperty = 'ingested_event',
    verifyingName = 'event',
}: {
    isOpen: boolean
    onClose: () => void
    sdk?: SDK
    sdkInstructionMap: SDKInstructionsMap
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
                <>
                    <header className="p-4 flex items-center gap-2">
                        <LemonButton icon={<IconArrowLeft />} onClick={onClose} size="xsmall">
                            All SDKs
                        </LemonButton>
                    </header>
                    <section className="p-4 flex flex-col h-full">
                        <div className="flex-grow overflow-y-auto pb-24">
                            <SDKSnippet sdk={sdk} sdkInstructions={sdkInstructions} />
                        </div>
                        <div className="sticky bottom-0 w-full bg-bg-light dark:bg-bg-depth p-2 flex justify-between items-center gap-2">
                            <RealtimeCheckIndicator
                                teamPropertyToVerify={verifyingProperty}
                                listeningForName={verifyingName}
                            />
                            <NextButton installationComplete={installationComplete} />
                        </div>
                    </section>
                </>
            )}
        </LemonModal>
    )
}
export function AlternativeSDKs({
    sdkInstructionMap,
    stepKey = OnboardingStepKey.INSTALL,
    listeningForName = 'event',
    teamPropertyToVerify = 'ingested_event',
}: SDKsProps): JSX.Element {
    const { setAvailableSDKInstructionsMap, selectSDK } = useActions(sdksLogic)
    const { sdks, selectedSDK } = useValues(sdksLogic)
    const [searchTerm, setSearchTerm] = useState('')
    const [selectedTag, setSelectedTag] = useState<SDKTag | null>(null)
    const [instructionsModalOpen, setInstructionsModalOpen] = useState(false)
    const { openSidePanel, closeSidePanel } = useActions(sidePanelStateLogic)
    const { selectedTab, sidePanelOpen } = useValues(sidePanelStateLogic)

    const installationComplete = useInstallationComplete(teamPropertyToVerify)

    useEffect(() => {
        setAvailableSDKInstructionsMap(sdkInstructionMap)
    }, [sdkInstructionMap, setAvailableSDKInstructionsMap])

    const filteredSDKs = sdks
        ?.filter((sdk) => (searchTerm ? sdk.name.toLowerCase().includes(searchTerm.toLowerCase()) : true))
        .filter((sdk) => (selectedTag === null ? true : sdk.tags?.includes(selectedTag)))

    const tags: string[] = ['All', ...Object.values(SDKTag)]

    return (
        <OnboardingStep
            title="Install"
            stepKey={stepKey}
            continueOverride={<NextButton installationComplete={installationComplete} />}
            actions={
                <RealtimeCheckIndicator
                    teamPropertyToVerify={teamPropertyToVerify}
                    listeningForName={listeningForName}
                />
            }
        >
            <div className="flex flex-col gap-y-4 mt-6">
                <div className="flex flex-col gap-y-2">
                    <div className="flex flex-row justify-between gap-4">
                        <LemonInput
                            value={searchTerm}
                            onChange={setSearchTerm}
                            placeholder="Search"
                            className="w-full max-w-sm"
                        />
                        <div className="flex flex-row gap-2">
                            <InviteMembersButton
                                type="primary"
                                size="small"
                                fullWidth={false}
                                text="Invite developer"
                            />
                            <LemonButton
                                size="small"
                                type="primary"
                                icon={<IconChatHelp />}
                                onClick={() =>
                                    selectedTab === SidePanelTab.Support && sidePanelOpen
                                        ? closeSidePanel()
                                        : openSidePanel(SidePanelTab.Support)
                                }
                            >
                                Get help
                            </LemonButton>
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
                        {filteredSDKs?.map((sdk) => (
                            <LemonCard
                                key={sdk.key}
                                className="p-4 cursor-pointer flex flex-col items-start justify-center"
                                onClick={() => {
                                    selectSDK(sdk)
                                    setInstructionsModalOpen(true)
                                }}
                            >
                                {typeof sdk.image === 'string' ? (
                                    <img src={sdk.image} className="w-8 h-8 mb-2" />
                                ) : typeof sdk.image === 'object' && 'default' in sdk.image ? (
                                    <img src={sdk.image.default} className="w-8 h-8 mb-2" />
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
                    verifyingProperty={teamPropertyToVerify}
                    verifyingName={listeningForName}
                />
            )}
        </OnboardingStep>
    )
}

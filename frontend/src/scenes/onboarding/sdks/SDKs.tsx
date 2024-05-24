import { IconArrowLeft, IconArrowRight, IconCheck } from '@posthog/icons'
import { LemonButton, LemonCard, LemonDivider, LemonSelect, Spinner } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { useWindowSize } from 'lib/hooks/useWindowSize'
import { useEffect, useState } from 'react'
import React from 'react'
import { liveEventsTableLogic } from 'scenes/events-management/live-events/liveEventsTableLogic'
import { teamLogic } from 'scenes/teamLogic'

import { InviteMembersButton } from '~/layout/navigation/TopBar/AccountPopover'
import { SDKInstructionsMap } from '~/types'

import { onboardingLogic, OnboardingStepKey } from '../onboardingLogic'
import { OnboardingStep } from '../OnboardingStep'
import { sdksLogic } from './sdksLogic'
import { SDKSnippet } from './SDKSnippet'

export function SDKs({
    sdkInstructionMap,
    stepKey = OnboardingStepKey.INSTALL,
    teamPropertyToVerify = 'ingested_event',
}: {
    usersAction?: string
    sdkInstructionMap: SDKInstructionsMap
    subtitle?: string
    stepKey?: OnboardingStepKey
    teamPropertyToVerify?: string
}): JSX.Element {
    const { loadCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)
    const { setSourceFilter, setSelectedSDK, setAvailableSDKInstructionsMap, setShowSideBySide, setPanel } =
        useActions(sdksLogic)
    const { sourceFilter, sdks, selectedSDK, sourceOptions, showSourceOptionsSelect, showSideBySide, panel } =
        useValues(sdksLogic)
    const { productKey, hasNextStep } = useValues(onboardingLogic)
    const { goToNextStep, completeOnboarding } = useActions(onboardingLogic)

    const [eventsFound, setEventsFound] = useState(false)

    const { filteredEvents } = useValues(liveEventsTableLogic)
    const { pauseStream } = useActions(liveEventsTableLogic)

    const { width } = useWindowSize()
    useEffect(() => {
        if (filteredEvents.length > 0) {
            setEventsFound(true)
            pauseStream()
        }
    }, [filteredEvents])

    useEffect(() => {
        const polling = setInterval(() => {
            loadCurrentTeam()
            if (currentTeam?.[teamPropertyToVerify]) {
                setEventsFound(true)
                clearInterval(polling)
            }
        }, 1500)

        return () => {
            clearInterval(polling)
        }
    }, [])

    const minimumSideBySideSize = 768

    useEffect(() => {
        setAvailableSDKInstructionsMap(sdkInstructionMap)
    }, [])

    useEffect(() => {
        width && setShowSideBySide(width > minimumSideBySideSize)
    }, [width])

    return (
        <OnboardingStep title="Install" stepKey={stepKey} continueOverride={<></>}>
            <div className="flex gap-x-8 mt-6">
                <div
                    className={`flex-col gap-y-2 flex-wrap gap-x-4 ${showSideBySide && 'min-w-[12.5rem] w-50'} ${
                        !showSideBySide && panel !== 'options' ? 'hidden' : 'flex'
                    }`}
                >
                    {showSourceOptionsSelect && (
                        <LemonSelect
                            allowClear
                            onChange={(v) => setSourceFilter(v)}
                            options={sourceOptions}
                            placeholder="Select a source type"
                            value={sourceFilter}
                            fullWidth
                        />
                    )}
                    {sdks?.map((sdk) => (
                        <React.Fragment key={`sdk-${sdk.key}`}>
                            <LemonButton
                                data-attr={`onboarding-sdk-${sdk.key}`}
                                active={selectedSDK?.key === sdk.key}
                                onClick={selectedSDK?.key !== sdk.key ? () => setSelectedSDK(sdk) : undefined}
                                fullWidth
                                icon={
                                    typeof sdk.image === 'string' ? (
                                        <img src={sdk.image} className="w-4" />
                                    ) : // storybook handles require() differently and returns an object, from which we can use the url in .default
                                    typeof sdk.image === 'object' && 'default' in sdk.image ? (
                                        <img src={sdk.image.default} className="w-4" />
                                    ) : (
                                        sdk.image
                                    )
                                }
                            >
                                {sdk.name}
                            </LemonButton>
                        </React.Fragment>
                    ))}
                    <LemonCard className="mt-6" hoverEffect={false}>
                        <h3 className="font-bold">Need help with this step?</h3>
                        <p>Invite a team member to help you get set up.</p>
                        <InviteMembersButton type="secondary" />
                    </LemonCard>
                </div>
                {selectedSDK && productKey && !!sdkInstructionMap[selectedSDK.key] && (
                    <div
                        className={`shrink min-w-[2rem] ${!showSideBySide && panel !== 'instructions' ? 'hidden' : ''}`}
                    >
                        {!showSideBySide && (
                            <LemonButton
                                icon={<IconArrowLeft />}
                                onClick={() => setPanel('options')}
                                className="mb-8"
                                type="secondary"
                            >
                                View all SDKs
                            </LemonButton>
                        )}
                        <SDKSnippet sdk={selectedSDK} sdkInstructions={sdkInstructionMap[selectedSDK.key]} />
                        <LemonDivider className="my-8" />
                        <div className="flex justify-between">
                            <div>
                                <h2 className="font-bold mb-4">Verify installation</h2>
                                <p className="flex items-center italic text-muted">
                                    {!eventsFound ? (
                                        <>
                                            <Spinner className="text-3xl mr-2" /> Verifying installation...
                                        </>
                                    ) : (
                                        <>
                                            <IconCheck className="text-xl text-success mr-2" /> Installation complete
                                        </>
                                    )}
                                </p>
                            </div>
                            <div>
                                {!showSideBySide && panel === 'options' ? (
                                    <></>
                                ) : !eventsFound ? (
                                    <LemonButton
                                        type="secondary"
                                        onClick={() => (!hasNextStep ? completeOnboarding() : goToNextStep())}
                                    >
                                        Skip installation
                                    </LemonButton>
                                ) : (
                                    <LemonButton
                                        data-attr="sdk-continue"
                                        sideIcon={hasNextStep ? <IconArrowRight /> : null}
                                        type="primary"
                                        status="alt"
                                        onClick={() => (!hasNextStep ? completeOnboarding() : goToNextStep())}
                                    >
                                        Continue
                                    </LemonButton>
                                )}
                            </div>
                        </div>
                    </div>
                )}
            </div>
        </OnboardingStep>
    )
}

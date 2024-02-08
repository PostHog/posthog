import { IconArrowLeft } from '@posthog/icons'
import { LemonButton, LemonCard, LemonSelect } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { useWindowSize } from 'lib/hooks/useWindowSize'
import { useEffect } from 'react'
import React from 'react'

import { InviteMembersButton } from '~/layout/navigation/TopBar/AccountPopover'
import { SDKInstructionsMap } from '~/types'

import { onboardingLogic, OnboardingStepKey } from '../onboardingLogic'
import { OnboardingStep } from '../OnboardingStep'
import { sdksLogic } from './sdksLogic'
import { SDKSnippet } from './SDKSnippet'

export function SDKs({
    sdkInstructionMap,
    stepKey = OnboardingStepKey.INSTALL,
}: {
    usersAction?: string
    sdkInstructionMap: SDKInstructionsMap
    subtitle?: string
    stepKey?: OnboardingStepKey
}): JSX.Element {
    const { setSourceFilter, setSelectedSDK, setAvailableSDKInstructionsMap, setShowSideBySide, setPanel } =
        useActions(sdksLogic)
    const { sourceFilter, sdks, selectedSDK, sourceOptions, showSourceOptionsSelect, showSideBySide, panel } =
        useValues(sdksLogic)
    const { productKey } = useValues(onboardingLogic)
    const { width } = useWindowSize()

    const minimumSideBySideSize = 768

    useEffect(() => {
        setAvailableSDKInstructionsMap(sdkInstructionMap)
    }, [])

    useEffect(() => {
        width && setShowSideBySide(width > minimumSideBySideSize)
    }, [width])

    return (
        <OnboardingStep
            title="Install"
            stepKey={stepKey}
            continueOverride={!showSideBySide && panel === 'options' ? <></> : undefined}
            // backActionOverride={!showSideBySide && panel === 'instructions' ? () => setPanel('options') : undefined}
        >
            <div className="flex gap-x-8 mt-8">
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
                        <InviteMembersButton type="primary" />
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
                    </div>
                )}
            </div>
        </OnboardingStep>
    )
}

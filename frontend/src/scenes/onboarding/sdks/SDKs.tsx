import { IconArrowLeft } from '@posthog/icons'
import { LemonButton, LemonCard, LemonDivider, LemonSelect } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { useWindowSize } from 'lib/hooks/useWindowSize'
import { useEffect } from 'react'
import React from 'react'

import { InviteMembersButton } from '~/layout/navigation/TopBar/SitePopover'
import { SDKInstructionsMap } from '~/types'

import { onboardingLogic, OnboardingStepKey } from '../onboardingLogic'
import { OnboardingStep } from '../OnboardingStep'
import { sdksLogic } from './sdksLogic'
import { SDKSnippet } from './SDKSnippet'

export function SDKs({
    usersAction,
    sdkInstructionMap,
    subtitle,
    stepKey = OnboardingStepKey.SDKS,
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
            title={`Where are you ${usersAction || 'collecting data'} from?`}
            subtitle={subtitle || 'Pick one or two to start and add more sources later.'}
            stepKey={stepKey}
            continueOverride={!showSideBySide && panel === 'options' ? <></> : undefined}
            backActionOverride={!showSideBySide && panel === 'instructions' ? () => setPanel('options') : undefined}
        >
            <LemonDivider className="my-8" />
            <div className="flex gap-x-8 mt-8">
                <div
                    className={`flex-col gap-y-2 flex-wrap gap-x-4 ${showSideBySide && 'min-w-50 w-50'} ${
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
                                status={selectedSDK?.key === sdk.key ? 'primary' : 'muted'}
                                active={selectedSDK?.key === sdk.key}
                                onClick={selectedSDK?.key !== sdk.key ? () => setSelectedSDK(sdk) : undefined}
                                fullWidth
                                icon={
                                    typeof sdk.image === 'string' ? <img src={sdk.image} className="w-4" /> : sdk.image
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
                    <div className={`shrink min-w-8 ${!showSideBySide && panel !== 'instructions' ? 'hidden' : ''}`}>
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

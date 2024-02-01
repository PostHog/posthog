import { IconArrowLeft, IconEye } from '@posthog/icons'
import { LemonButton, LemonCard, LemonSelect, Link, Spinner } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { LaptopHog1 } from 'lib/components/hedgehogs'
import { useWindowSize } from 'lib/hooks/useWindowSize'
import { useEffect } from 'react'
import React from 'react'

import { InviteMembersButton } from '~/layout/navigation/TopBar/AccountPopover'
import { ProductKey, SDKInstructionsMap } from '~/types'

import { onboardingLogic, OnboardingStepKey } from '../onboardingLogic'
import { OnboardingStep } from '../OnboardingStep'
import { multiInstallProducts, sdksLogic } from './sdksLogic'
import { SDKSnippet } from './SDKSnippet'

export function SDKs({
    sdkInstructionMap,
    stepKey = OnboardingStepKey.SDKS,
}: {
    usersAction?: string
    sdkInstructionMap: SDKInstructionsMap
    subtitle?: string
    stepKey?: OnboardingStepKey
}): JSX.Element {
    const {
        setSourceFilter,
        setSelectedSDK,
        setAvailableSDKInstructionsMap,
        setShowSideBySide,
        setPanel,
        setHasSnippetEvents,
    } = useActions(sdksLogic)
    const {
        sourceFilter,
        sdks,
        selectedSDK,
        sourceOptions,
        showSourceOptionsSelect,
        showSideBySide,
        panel,
        hasSnippetEvents,
    } = useValues(sdksLogic)
    const { productKey, product, isFirstProductOnboarding } = useValues(onboardingLogic)
    const { width } = useWindowSize()
    const minimumSideBySideSize = 768

    useEffect(() => {
        setAvailableSDKInstructionsMap(sdkInstructionMap)
    }, [])

    useEffect(() => {
        width && setShowSideBySide(width > minimumSideBySideSize)
    }, [width])

    return !isFirstProductOnboarding && hasSnippetEvents === null ? (
        <OnboardingStep title="Checking for snippet installation..." stepKey={stepKey} hedgehog={<LaptopHog1 />}>
            <div className="flex justify-center mt-6">
                <Spinner className="text-xl" />
            </div>
        </OnboardingStep>
    ) : !isFirstProductOnboarding && hasSnippetEvents ? (
        <OnboardingStep
            title={`Huzzah! You've already installed PostHog.js.`}
            stepKey={stepKey}
            hedgehog={<LaptopHog1 />}
        >
            <p>{product?.name} works with PostHog.js with no extra installation required. Easy peasy, huh?</p>
            {multiInstallProducts.includes(productKey as ProductKey) && (
                <p>
                    Need to install somewhere else?{' '}
                    <Link onClick={() => setHasSnippetEvents(false)}>
                        <IconEye /> Show SDK instructions
                    </Link>
                </p>
            )}
        </OnboardingStep>
    ) : (
        <OnboardingStep
            title="Install"
            stepKey={stepKey}
            continueOverride={!showSideBySide && panel === 'options' ? <></> : undefined}
            backActionOverride={!showSideBySide && panel === 'instructions' ? () => setPanel('options') : undefined}
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

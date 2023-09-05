import { LemonButton, LemonDivider, LemonSelect } from '@posthog/lemon-ui'
import { sdksLogic } from './sdksLogic'
import { useActions, useValues } from 'kea'
import { OnboardingStep } from '../OnboardingStep'
import { SDKSnippet } from './SDKSnippet'
import { onboardingLogic } from '../onboardingLogic'
import { useEffect } from 'react'
import React from 'react'
import { SDKInstructionsMap } from '~/types'

export function SDKs({
    usersAction,
    sdkInstructionMap,
}: {
    usersAction?: string
    sdkInstructionMap: SDKInstructionsMap
}): JSX.Element {
    const { setSourceFilter, setSelectedSDK, setAvailableSDKInstructionsMap } = useActions(sdksLogic)
    const { sourceFilter, sdks, selectedSDK, sourceOptions } = useValues(sdksLogic)
    const { productKey } = useValues(onboardingLogic)

    useEffect(() => {
        setAvailableSDKInstructionsMap(sdkInstructionMap)
    }, [])

    return (
        <OnboardingStep
            title={`Where are you ${usersAction || 'collecting data'} from?`}
            subtitle="Pick one or two to start and add more sources later."
        >
            <LemonDivider className="my-8" />
            <div className="flex gap-x-8 mt-8">
                <div className={`flex flex-col gap-y-2 flex-wrap gap-x-4 min-w-50`}>
                    {sourceOptions.length > 1 && (
                        <LemonSelect
                            allowClear
                            onChange={(v) => setSourceFilter(v)}
                            options={sourceOptions}
                            placeholder="Select a source type"
                            value={sourceFilter}
                            className="w-full"
                        />
                    )}
                    {sdks?.map((sdk) => (
                        <React.Fragment key={`sdk-${sdk.key}`}>
                            {selectedSDK?.key == sdk.key ? (
                                <LemonButton
                                    type="secondary"
                                    className="flex"
                                    icon={
                                        <div className="w-4">
                                            {typeof sdk.image === 'string' ? (
                                                <img src={sdk.image} className="w-4" />
                                            ) : (
                                                sdk.image
                                            )}
                                        </div>
                                    }
                                >
                                    {sdk.name}
                                </LemonButton>
                            ) : (
                                <LemonButton
                                    type="tertiary"
                                    status="muted"
                                    className="flex"
                                    onClick={() => setSelectedSDK(sdk)}
                                    icon={
                                        <div className="w-4">
                                            {typeof sdk.image === 'string' ? (
                                                <img src={sdk.image} className="w-4" />
                                            ) : (
                                                sdk.image
                                            )}
                                        </div>
                                    }
                                >
                                    {sdk.name}
                                </LemonButton>
                            )}
                        </React.Fragment>
                    ))}
                </div>
                {selectedSDK && productKey && (
                    <div className="shrink min-w-8">
                        <SDKSnippet sdk={selectedSDK} sdkInstructionMap={sdkInstructionMap} />
                    </div>
                )}
            </div>
        </OnboardingStep>
    )
}

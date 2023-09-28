import { LemonButton, LemonCard, LemonDivider, LemonSelect } from '@posthog/lemon-ui'
import { sdksLogic } from './sdksLogic'
import { useActions, useValues } from 'kea'
import { OnboardingStep } from '../OnboardingStep'
import { SDKSnippet } from './SDKSnippet'
import { onboardingLogic } from '../onboardingLogic'
import { useEffect } from 'react'
import React from 'react'
import { SDKInstructionsMap } from '~/types'
import { InviteMembersButton } from '~/layout/navigation/TopBar/SitePopover'

export function SDKs({
    usersAction,
    sdkInstructionMap,
    subtitle,
}: {
    usersAction?: string
    sdkInstructionMap: SDKInstructionsMap
    subtitle?: string
}): JSX.Element {
    const { setSourceFilter, setSelectedSDK, setAvailableSDKInstructionsMap } = useActions(sdksLogic)
    const { sourceFilter, sdks, selectedSDK, sourceOptions, showSourceOptionsSelect } = useValues(sdksLogic)
    const { productKey } = useValues(onboardingLogic)

    useEffect(() => {
        setAvailableSDKInstructionsMap(sdkInstructionMap)
    }, [])

    return (
        <OnboardingStep
            title={`Where are you ${usersAction || 'collecting data'} from?`}
            subtitle={subtitle || 'Pick one or two to start and add more sources later.'}
        >
            <LemonDivider className="my-8" />
            <div className="flex gap-x-8 mt-8">
                <div className={`flex flex-col gap-y-2 flex-wrap gap-x-4 min-w-50 w-50`}>
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
                                status={selectedSDK?.key === sdk.key ? 'primary' : 'muted-alt'}
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
                    <div className="shrink min-w-8">
                        <SDKSnippet sdk={selectedSDK} sdkInstructions={sdkInstructionMap[selectedSDK.key]} />
                    </div>
                )}
            </div>
        </OnboardingStep>
    )
}

import { LemonButton, LemonDivider, LemonInput, LemonSelect } from '@posthog/lemon-ui'
import { sdksLogic } from './sdksLogic'
import { LemonCard } from 'lib/lemon-ui/LemonCard/LemonCard'
import { useActions, useValues } from 'kea'
import { OnboardingStep } from '../OnboardingStep'
import { SDKSnippet } from './SDKSnippet'
import { onboardingLogic } from '../onboardingLogic'
import { IconClose } from 'lib/lemon-ui/icons'

export function SDKs({ usersAction }: { usersAction?: string }): JSX.Element {
    const { setSourceFilter, setSelectedSDK } = useActions(sdksLogic)
    const { sourceFilter, sdks, selectedSDK, sourceOptions } = useValues(sdksLogic)
    const { productKey } = useValues(onboardingLogic)

    return (
        <OnboardingStep
            title={`Where are you ${usersAction || 'collecting data'} from?`}
            subtitle="Pick one to start and add more sources later."
        >
            <div className="flex gap-x-4">
                <LemonInput placeholder="Search for a source" type="search" />
                {sourceOptions.length > 1 && (
                    <LemonSelect
                        allowClear
                        onChange={(v) => setSourceFilter(v)}
                        options={sourceOptions}
                        placeholder="Select a source type"
                        value={sourceFilter}
                    />
                )}
            </div>
            <div className="flex flex-wrap gap-x-4 gap-y-4 mt-8 justify-center">
                {sdks?.map((sdk) => (
                    <LemonCard
                        className="w-32 flex flex-col items-center text-center"
                        key={'sdk-option-' + sdk.key}
                        onClick={() => setSelectedSDK(sdk)}
                        focused={selectedSDK?.key == sdk.key}
                    >
                        {selectedSDK?.key == sdk.key && (
                            <div className="flex justify-end w-full">
                                <LemonButton
                                    icon={<IconClose className="text-xs" />}
                                    type="tertiary"
                                    size="small"
                                    className="-mt-4 -mr-4"
                                    onClick={(e) => {
                                        e.stopPropagation()
                                        setSelectedSDK(null)
                                    }}
                                    status="muted"
                                />
                            </div>
                        )}
                        <div className="h-8 mb-4">
                            {typeof sdk.image === 'string' ? <img src={sdk.image} className="w-8" /> : sdk.image}
                        </div>
                        <h4 className="mb-0 leading-4">{sdk.name}</h4>
                    </LemonCard>
                ))}
            </div>
            {selectedSDK && productKey && (
                <>
                    <LemonDivider className="my-8" />
                    <SDKSnippet sdk={selectedSDK} productKey={productKey} />
                </>
            )}
        </OnboardingStep>
    )
}

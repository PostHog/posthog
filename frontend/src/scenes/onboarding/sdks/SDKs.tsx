import { LemonDivider, LemonInput, LemonSelect } from '@posthog/lemon-ui'
import { sdksLogic } from './sdksLogic'
import { LemonCard } from 'lib/lemon-ui/LemonCard/LemonCard'
import { useActions, useValues } from 'kea'
import { OnboardingStep } from '../OnboardingStep'
import { SDKSnippet } from './SDKSnippet'
import { onboardingLogic } from '../onboardingLogic'
import { useEffect } from 'react'

export function SDKs({ usersAction }: { usersAction?: string }): JSX.Element {
    const { setSourceFilter, setSelectedSDK, setSourceOptions } = useActions(sdksLogic)
    const { sourceFilter, sdks, selectedSDK, sourceOptions } = useValues(sdksLogic)
    const { productKey } = useValues(onboardingLogic)
    useEffect(() => {
        // get the unique tags from the sdks and put them in an array of objects with label (capitalized value) and value
        sdks &&
            setSourceOptions(
                sdks
                    ?.flatMap((sdk) => sdk.tags)
                    .map((tag) => ({
                        label: tag.charAt(0).toUpperCase() + tag.slice(1),
                        value: tag,
                    }))
            )
    }, [sdks])

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
                        <div className="h-8 mb-4">
                            <img src={sdk.image} className="w-8" />
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

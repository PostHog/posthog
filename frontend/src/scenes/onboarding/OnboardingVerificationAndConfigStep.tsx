import { LemonDivider, LemonSelect, LemonSwitch, Spinner } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { BlushingHog } from 'lib/components/hedgehogs'
import { useInterval } from 'lib/hooks/useInterval'
import { capitalizeFirstLetter } from 'lib/utils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { useEffect } from 'react'
import { teamLogic } from 'scenes/teamLogic'

import { OnboardingStepKey } from './onboardingLogic'
import { onboardingProductConfigurationLogic, ProductConfigOption } from './onboardingProductConfigurationLogic'
import { OnboardingStep } from './OnboardingStep'

export const OnboardingVerificationAndConfigStep = ({
    listeningForName,
    teamPropertyToVerify,
    stepKey = OnboardingStepKey.VERIFY_AND_CONFIGURE,
    options,
}: {
    listeningForName: string
    teamPropertyToVerify: string
    stepKey?: OnboardingStepKey
    options: ProductConfigOption[]
}): JSX.Element => {
    const { loadCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)
    const { reportIngestionContinueWithoutVerifying } = useActions(eventUsageLogic)
    const { configOptions } = useValues(onboardingProductConfigurationLogic)
    const { setConfigOptions, saveConfiguration } = useActions(onboardingProductConfigurationLogic)
    useEffect(() => {
        setConfigOptions(options)
    }, [])

    useInterval(() => {
        if (!currentTeam?.[teamPropertyToVerify]) {
            loadCurrentTeam()
        }
    }, 2000)

    return (
        <OnboardingStep
            title="Configure"
            stepKey={stepKey}
            continueAction={() => {
                !currentTeam?.[teamPropertyToVerify] && reportIngestionContinueWithoutVerifying()
                saveConfiguration()
            }}
        >
            <h3>Verifying Installation...</h3>
            <LemonDivider />
            {!currentTeam?.[teamPropertyToVerify] ? (
                <>
                    <div className="flex items-center pb-8 gap-4">
                        <Spinner className="text-3xl" />
                        <div>{`Listening for ${listeningForName}s...`}</div>
                    </div>
                </>
            ) : (
                <>
                    <div className="flex items-center pb-8 gap-4">
                        <div className="max-w-20 -scale-x-100">
                            <BlushingHog className="h-full w-full" />
                        </div>
                        <div>{`${capitalizeFirstLetter(listeningForName)}s successfully sent!`}</div>
                    </div>
                </>
            )}

            <h3>Options</h3>
            <LemonDivider />
            {configOptions?.map((option: ProductConfigOption) => (
                <div className="my-4" key={option.teamProperty}>
                    {option.type == 'toggle' ? (
                        <>
                            <LemonSwitch
                                data-attr="opt-in-session-recording-switch"
                                onChange={(checked) => {
                                    setConfigOptions(
                                        configOptions.map((o) =>
                                            o.teamProperty === option.teamProperty ? { ...o, value: checked } : o
                                        )
                                    )
                                }}
                                label={option.title}
                                fullWidth={true}
                                labelClassName="text-base font-semibold"
                                checked={option.value || false}
                            />
                            <p className="prompt-text ml-0 mr-9">{option.description}</p>
                        </>
                    ) : (
                        <>
                            <label className="text-base font-semibold">{option.title}</label>
                            <div className="flex justify-between items-center mb-1 gap-x-4">
                                <p className="prompt-text m-0">{option.description}</p>
                                <LemonSelect
                                    dropdownMatchSelectWidth={false}
                                    onChange={(v) => {
                                        setConfigOptions(
                                            configOptions.map((o) =>
                                                o.teamProperty === option.teamProperty ? { ...o, value: v } : o
                                            )
                                        )
                                    }}
                                    options={option.selectOptions || []}
                                    value={option.value}
                                />
                            </div>
                        </>
                    )}
                </div>
            ))}
        </OnboardingStep>
    )
}

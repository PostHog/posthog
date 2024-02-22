import { LemonSelect, LemonSwitch } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { OnboardingStepKey } from './onboardingLogic'
import { onboardingProductConfigurationLogic, ProductConfigOption } from './onboardingProductConfigurationLogic'
import { OnboardingStep } from './OnboardingStep'

export const OnboardingProductConfiguration = ({
    stepKey = OnboardingStepKey.PRODUCT_CONFIGURATION,
    options,
}: {
    stepKey?: OnboardingStepKey
    options: ProductConfigOption[]
}): JSX.Element | null => {
    const { configOptions } = useValues(onboardingProductConfigurationLogic)
    const { setConfigOptions, saveConfiguration } = useActions(onboardingProductConfigurationLogic)
    useEffect(() => {
        setConfigOptions(options)
    }, [])

    return configOptions ? (
        <OnboardingStep title="Set up your configuration" stepKey={stepKey} continueAction={saveConfiguration}>
            {configOptions?.map((option: ProductConfigOption) => (
                <div className="my-8" key={option.teamProperty}>
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
                                labelClassName="text-base font-semibold -ml-2"
                                checked={option.value || false}
                            />
                            <p className="prompt-text ml-0">{option.description}</p>
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
    ) : null
}

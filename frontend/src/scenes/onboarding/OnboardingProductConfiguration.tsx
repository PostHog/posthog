import { LemonDivider, LemonSelect, LemonSwitch } from '@posthog/lemon-ui'
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
            <h2 className="pt-2">Options</h2>
            {configOptions?.map((option: ProductConfigOption) => (
                <>
                    <LemonDivider className="my-4" />
                    <div className="grid grid-cols-[minmax(min-content,_2fr)_1fr_minmax(min-content,_3fr)] items-center">
                        <label className="text-base font-semibold">{option.title}</label>
                        {option.type == 'toggle' ? (
                            <LemonSwitch
                                data-attr="opt-in-session-recording-switch"
                                onChange={(checked) => {
                                    setConfigOptions(
                                        configOptions.map((o) =>
                                            o.teamProperty === option.teamProperty ? { ...o, value: checked } : o
                                        )
                                    )
                                }}
                                className="self-center"
                                label={option.title}
                                fullWidth={true}
                                labelClassName="text-base font-semibold -ml-2"
                                checked={option.value || false}
                            />
                        ) : (
                            <div className="flex justify-between items-center mb-1 gap-x-4">
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
                        )}
                        <p className="prompt-text ml-0 mb-0">{option.description}</p>
                    </div>
                </>
            ))}
        </OnboardingStep>
    ) : null
}

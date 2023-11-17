import { OnboardingStep } from './OnboardingStep'
import { OnboardingStepKey } from './onboardingLogic'
import { useActions, useValues } from 'kea'
import { LemonSwitch } from '@posthog/lemon-ui'
import { useEffect } from 'react'
import { ProductConfigOption, onboardingProductConfigurationLogic } from './onboardingProductConfigurationLogic'

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
        <OnboardingStep title={`Set up your configuration`} stepKey={stepKey} continueAction={saveConfiguration}>
            {configOptions?.map((option: ProductConfigOption) => (
                <div className="my-8" key={option.teamProperty}>
                    <LemonSwitch
                        data-attr="opt-in-session-recording-switch"
                        onChange={(checked) => {
                            setConfigOptions(
                                configOptions
                                    .filter((o) => o.teamProperty !== option.teamProperty)
                                    .concat({ ...option, value: checked })
                            )
                        }}
                        label={option.title}
                        fullWidth={true}
                        labelClassName={'text-base font-semibold'}
                        checked={option.value || false}
                    />
                    <p className="prompt-text ml-0">{option.description}</p>
                </div>
            ))}
        </OnboardingStep>
    ) : null
}

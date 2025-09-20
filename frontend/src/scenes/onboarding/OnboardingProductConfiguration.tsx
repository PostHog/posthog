import { useActions, useValues } from 'kea'
import React, { useEffect, useRef } from 'react'

import { LemonDivider, LemonSelect, LemonSwitch } from '@posthog/lemon-ui'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'

import { OnboardingStepKey, ProductKey } from '~/types'

import { OnboardingStep } from './OnboardingStep'
import { ProductConfigOption, onboardingProductConfigurationLogic } from './onboardingProductConfigurationLogic'

type ConfigType = 'toggle' | 'select'
type PluginType = 'plugin'
type ConfigOption =
    | {
          title: string
          description?: string
          type: ConfigType
          selectOptions?: { label: string; value: string | number }[]
          value: boolean | string | number
          onChange: (newValue: boolean | string | number) => void
      }
    | {
          title: string
          description?: string
          type: PluginType
          value: boolean
          onChange: (newValue: boolean) => void
      }

export const OnboardingProductConfiguration = ({
    stepKey = OnboardingStepKey.PRODUCT_CONFIGURATION,
    options,
}: {
    stepKey?: OnboardingStepKey
    options: (ProductConfigOption | undefined)[]
    // which product is being configured
    product?: ProductKey
}): JSX.Element | null => {
    const { configOptions } = useValues(onboardingProductConfigurationLogic)
    const { setConfigOptions, saveConfiguration } = useActions(onboardingProductConfigurationLogic)

    const configOptionsRef = useRef(configOptions)

    useEffect(() => {
        configOptionsRef.current = configOptions
    }, [configOptions])

    useOnMountEffect(() => {
        setConfigOptions(options.filter((option): option is ProductConfigOption => !!option))
    })

    const combinedList: ConfigOption[] = configOptions
        .filter((option) => option.visible)
        .map((option) => ({
            title: option.title,
            description: option.description,
            type: option.type as ConfigType,
            selectOptions: option.selectOptions,
            value: option.value,
            onChange: (newValue: boolean | string | number) => {
                // Use the current value from the ref to ensure that onChange always accesses
                // the latest state of configOptions, preventing the closure from using stale data.
                const updatedConfigOptions = configOptionsRef.current.map((o) => {
                    if (o.teamProperty === option.teamProperty) {
                        return { ...o, value: newValue }
                    }

                    return o
                })

                setConfigOptions(updatedConfigOptions)
            },
        }))

    return combinedList.length > 0 ? (
        <OnboardingStep title="Set up your configuration" stepKey={stepKey} onContinue={saveConfiguration}>
            <div className="mt-6">
                <h2 className="pt-2">Options</h2>
                {combinedList.map((item, idx) => (
                    <React.Fragment key={idx}>
                        <LemonDivider className="my-4" />
                        <div className="grid grid-cols-3 gap-4">
                            <div className="col-span-2">
                                <label className="text-base font-semibold">{item.title}</label>
                                <p className="mt-2 mb-0 prompt-text">{item.description}</p>
                            </div>
                            <div className="flex justify-end">
                                {item.type === 'toggle' ? (
                                    <LemonSwitch
                                        onChange={item.onChange}
                                        className="justify-end"
                                        fullWidth={true}
                                        checked={(item.value as boolean) || false}
                                    />
                                ) : item.type === 'plugin' ? (
                                    <LemonSwitch
                                        onChange={item.onChange}
                                        className="justify-end"
                                        fullWidth={true}
                                        checked={item.value || false}
                                    />
                                ) : (
                                    <div className="flex gap-x-4 justify-end items-center mb-1">
                                        <LemonSelect
                                            dropdownMatchSelectWidth={false}
                                            onChange={item.onChange}
                                            options={item.selectOptions || []}
                                            value={item.value}
                                        />
                                    </div>
                                )}
                            </div>
                        </div>
                    </React.Fragment>
                ))}
            </div>
        </OnboardingStep>
    ) : null
}

import { useActions, useValues } from 'kea'
import React, { useEffect, useRef } from 'react'

import { LemonDivider } from '@posthog/lemon-ui'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'

import { OnboardingStepKey } from '~/types'

import { OnboardingStepComponentType } from './onboardingLogic'
import { ProductConfigOption, onboardingProductConfigurationLogic } from './onboardingProductConfigurationLogic'
import {
    OnboardingProductConfigurationOption,
    OnboardingProductConfigurationOptionProps,
} from './OnboardingProductConfigurationOption'
import { OnboardingStep } from './OnboardingStep'

interface OnboardingProductConfigurationProps {
    options: ProductConfigOption[]
}

export const OnboardingProductConfiguration: OnboardingStepComponentType<OnboardingProductConfigurationProps> = ({
    options,
}) => {
    const { configOptions } = useValues(onboardingProductConfigurationLogic)
    const { setConfigOptions, saveConfiguration } = useActions(onboardingProductConfigurationLogic)

    const configOptionsRef = useRef(configOptions)

    useEffect(() => {
        configOptionsRef.current = configOptions
    }, [configOptions])

    useOnMountEffect(() => {
        setConfigOptions(options)
    })

    const combinedList: OnboardingProductConfigurationOptionProps[] = configOptions
        .filter((option) => option.visible)
        .map((option) => ({
            teamProperty: option.teamProperty,
            title: option.title,
            description: option.description,
            type: option.type,
            selectOptions: option.type === 'select' ? option.selectOptions : undefined,
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
        <OnboardingStep
            title="Set up your configuration"
            stepKey={OnboardingStepKey.PRODUCT_CONFIGURATION}
            onContinue={saveConfiguration}
        >
            <div className="mt-6">
                <h2 className="pt-2">Options</h2>
                {combinedList.map((item) => (
                    <React.Fragment key={item.teamProperty}>
                        <LemonDivider className="my-4" />
                        <OnboardingProductConfigurationOption {...item} />
                    </React.Fragment>
                ))}
            </div>
        </OnboardingStep>
    ) : null
}

OnboardingProductConfiguration.stepKey = OnboardingStepKey.PRODUCT_CONFIGURATION

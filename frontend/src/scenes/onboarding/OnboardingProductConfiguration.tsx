import { LemonDivider, LemonSelect, LemonSwitch } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import React, { useEffect, useRef } from 'react'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'

import { OnboardingStepKey } from './onboardingLogic'
import { onboardingProductConfigurationLogic, ProductConfigOption } from './onboardingProductConfigurationLogic'
import { OnboardingStep } from './OnboardingStep'

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

interface PluginContent {
    title: string
    description: string
}
type PluginContentMapping = Record<string, PluginContent>
const pluginContentMapping: PluginContentMapping = {
    GeoIP: {
        title: 'Capture location information',
        description:
            'Enrich PostHog events and persons with IP location data. This is useful for understanding where your users are coming from. This setting can be found under the data pipelines apps.',
    },
}

export const OnboardingProductConfiguration = ({
    stepKey = OnboardingStepKey.PRODUCT_CONFIGURATION,
    options,
}: {
    stepKey?: OnboardingStepKey
    options: ProductConfigOption[]
}): JSX.Element | null => {
    const { configOptions } = useValues(onboardingProductConfigurationLogic)
    const { defaultEnabledPlugins } = useValues(pluginsLogic)
    const { setConfigOptions, saveConfiguration } = useActions(onboardingProductConfigurationLogic)
    const { toggleEnabled } = useActions(pluginsLogic)

    const configOptionsRef = useRef(configOptions)

    useEffect(() => {
        configOptionsRef.current = configOptions
    }, [configOptions])

    useEffect(() => {
        setConfigOptions(options)
    }, [])

    const combinedList: ConfigOption[] = [
        ...configOptions.map((option) => ({
            title: option.title,
            description: option.description,
            type: option.type as ConfigType,
            selectOptions: option.selectOptions,
            value: option.value,
            onChange: (newValue: boolean | string | number) => {
                // Use the current value from the ref to ensure that onChange always accesses
                // the latest state of configOptions, preventing the closure from using stale data.
                const updatedConfigOptions = configOptionsRef.current.map((o) =>
                    o.teamProperty === option.teamProperty ? { ...o, value: newValue } : o
                )
                setConfigOptions(updatedConfigOptions)
            },
        })),
        ...defaultEnabledPlugins.map((plugin) => {
            const pluginContent = pluginContentMapping[plugin.name]
            return {
                title: pluginContent?.title || plugin.name,
                description: pluginContent?.description || plugin.description,
                type: 'plugin' as PluginType,
                value: plugin.pluginConfig?.enabled || false,
                onChange: (newValue: boolean) => {
                    toggleEnabled({
                        id: plugin.pluginConfig?.id,
                        enabled: newValue,
                    })
                },
            }
        }),
    ]

    return combinedList.length > 0 ? (
        <OnboardingStep title="Set up your configuration" stepKey={stepKey} continueAction={saveConfiguration}>
            <div className="mt-6">
                <h2 className="pt-2">Options</h2>
                {combinedList.map((item, idx) => (
                    <React.Fragment key={idx}>
                        <LemonDivider className="my-4" />
                        <div className="grid gap-4 grid-cols-3">
                            <div className="col-span-2">
                                <label className="text-base font-semibold">{item.title}</label>
                                <p className="prompt-text mt-2 mb-0 ">{item.description}</p>
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
                                    <div className="flex justify-between items-center mb-1 gap-x-4">
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

import { LemonDivider, LemonSelect, LemonSwitch } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import React, { useEffect } from 'react'
import { PluginImage } from 'scenes/plugins/plugin/PluginImage'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { PluginRepositoryEntry, PluginTypeWithConfig } from 'scenes/plugins/types'

import { PluginType } from '~/types'

import { OnboardingStepKey } from './onboardingLogic'
import { onboardingProductConfigurationLogic, ProductConfigOption } from './onboardingProductConfigurationLogic'
import { OnboardingStep } from './OnboardingStep'

function AppView({ plugin }: { plugin: PluginTypeWithConfig | PluginType | PluginRepositoryEntry }): JSX.Element {
    const { toggleEnabled } = useActions(pluginsLogic)

    const pluginConfig = 'pluginConfig' in plugin ? plugin.pluginConfig : null

    return (
        <div className="grid gap-4 grid-cols-3">
            <div className="flex items-center gap-4 col-span-2">
                <PluginImage plugin={plugin} />
                <div>
                    <div className="flex gap-2 items-center">
                        <span className="text-base font-semibold">{plugin.name}</span>
                    </div>
                    <div className="prompt-text ml-0 mb-0">{plugin.description}</div>
                </div>
            </div>

            <div className="flex gap-2 whitespace-nowrap items-center justify-end">
                <LemonSwitch
                    data-attr="opt-in-session-recording-switch"
                    onChange={(checked) => {
                        toggleEnabled({
                            id: pluginConfig?.id,
                            enabled: checked,
                        })
                    }}
                    className="justify-end"
                    fullWidth={true}
                    checked={pluginConfig?.enabled || false}
                />
            </div>
        </div>
    )
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

    useEffect(() => {
        setConfigOptions(options)
    }, [])

    return configOptions ? (
        <OnboardingStep title="Set up your configuration" stepKey={stepKey} continueAction={saveConfiguration}>
            <h2 className="pt-2">Options</h2>
            {configOptions?.map((option: ProductConfigOption, idx) => (
                <React.Fragment key={idx}>
                    <LemonDivider className="my-4" />
                    <div className="grid gap-4 grid-cols-3">
                        <div className="col-span-2">
                            <label className="text-base font-semibold">{option.title}</label>
                            <p className="prompt-text ml-0 mb-0">{option.description}</p>
                        </div>
                        <div className="flex justify-end">
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
                                    className="justify-end"
                                    fullWidth={true}
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
                        </div>
                    </div>
                </React.Fragment>
            ))}

            <h2 className="mt-8">Plugins</h2>
            <LemonDivider className="my-4" />
            {defaultEnabledPlugins.map((plugin, idx) => (
                <AppView key={idx} plugin={plugin} />
            ))}
        </OnboardingStep>
    ) : null
}

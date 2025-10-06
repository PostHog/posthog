import { actions, connect, kea, listeners, path, reducers } from 'kea'

import { LemonSelectOptions } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'

import { TeamType } from '~/types'

import type { onboardingProductConfigurationLogicType } from './onboardingProductConfigurationLogicType'

export interface ProductConfigOptionBase {
    title: string
    description: string
    teamProperty: keyof TeamType
    visible: boolean
}

export interface ProductConfigurationToggle extends ProductConfigOptionBase {
    type: 'toggle'
    /** Sets the initial value. Use a team setting to reflect current state, or a static value to set a default. */
    value: boolean
    /** If true, the value is inverted when saving, used for 'opt_out' type settings */
    inverseToggle?: boolean
}

export interface ProductConfigurationSelect extends ProductConfigOptionBase {
    type: 'select'
    /** Sets the initial value. Use a team setting to reflect current state, or a static value to set a default. */
    value: string | number | null
    selectOptions: LemonSelectOptions<any>
    onChange?: (value: string | number | null) => Partial<TeamType>
}

export type ProductConfigOption = ProductConfigurationToggle | ProductConfigurationSelect

export const onboardingProductConfigurationLogic = kea<onboardingProductConfigurationLogicType>([
    path(() => ['scenes', 'onboarding', 'onboardingProductConfigurationLogic']),
    connect(() => ({
        actions: [teamLogic, ['updateCurrentTeam']],
    })),
    actions({
        setConfigOptions: (configOptions: ProductConfigOption[]) => ({ configOptions }),
        saveConfiguration: true,
    }),
    reducers(() => ({
        configOptions: [
            [],
            {
                setConfigOptions: (_, { configOptions }) => configOptions,
            },
        ],
    })),
    listeners(({ values, actions }) => ({
        saveConfiguration: async () => {
            const updateConfig: Record<string, any> = {}

            values.configOptions.forEach((configOption) => {
                if (configOption.onChange) {
                    const changes = configOption.onChange(configOption.value)
                    Object.assign(updateConfig, changes)
                } else {
                    const value = configOption.inverseToggle ? !configOption.value : configOption.value

                    updateConfig[configOption.teamProperty] = value
                }
            })

            actions.updateCurrentTeam(updateConfig as Partial<TeamType>)
        },
    })),
])

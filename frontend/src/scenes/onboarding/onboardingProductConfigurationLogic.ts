import { actions, kea, path, reducers, listeners, connect } from 'kea'

import type { onboardingProductConfigurationLogicType } from './onboardingProductConfigurationLogicType'
import { teamLogic } from 'scenes/teamLogic'

export interface ProductConfigOption {
    title: string
    description: string
    teamProperty: string
    value?: boolean
    type?: 'toggle'
    /** If true, the value is inverted when saving, used for 'opt_out' type settings */
    inverseToggle?: boolean
}

export const onboardingProductConfigurationLogic = kea<onboardingProductConfigurationLogicType>([
    path(() => ['scenes', 'onboarding', 'onboardingProductConfigurationLogic']),
    connect({
        actions: [teamLogic, ['updateCurrentTeam']],
    }),
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
            const updateConfig = {}
            values.configOptions.forEach((configOption) => {
                updateConfig[configOption.teamProperty] = configOption.inverseToggle
                    ? !configOption.value
                    : configOption.value
            })
            actions.updateCurrentTeam(updateConfig)
        },
    })),
])

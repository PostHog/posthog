import { actions, connect, kea, listeners, path, reducers } from 'kea'
import { teamLogic } from 'scenes/teamLogic'

import type { onboardingProductConfigurationLogicType } from './onboardingProductConfigurationLogicType'

export interface ProductConfigOption {
    title: string
    description: string
    teamProperty: string
    /** Sets the initial value. Use a team setting to reflect current state, or a boolean to set a default. */
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

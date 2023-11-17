import { actions, kea, path, reducers } from 'kea'

import type { onboardingProductConfigurationLogicType } from './onboardingProductConfigurationLogicType'

export interface ProductConfigOption {
    title: string
    description: string
    key: string
    value?: boolean
}

export const onboardingProductConfigurationLogic = kea<onboardingProductConfigurationLogicType>([
    path(() => ['scenes', 'onboarding', 'onboardingProductConfigurationLogic']),
    actions({
        setConfigOptions: (configOptions: ProductConfigOption[]) => ({ configOptions }),
    }),
    reducers(() => ({
        configOptions: [
            [],
            {
                setConfigOptions: (_, { configOptions }) => configOptions,
            },
        ],
    })),
])

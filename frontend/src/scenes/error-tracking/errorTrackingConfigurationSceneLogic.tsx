import { actions, kea, path, reducers } from 'kea'

import type { errorTrackingConfigurationSceneLogicType } from './errorTrackingConfigurationSceneLogicType'

export enum ConfigurationTab {
    Alerts = 'alerts',
    SymbolSets = 'symbol_sets',
}

export const errorTrackingConfigurationSceneLogic = kea<errorTrackingConfigurationSceneLogicType>([
    path(['scenes', 'error-tracking', 'errorTrackingLogic']),

    actions({
        setTab: (tab: ConfigurationTab) => ({ tab }),
    }),
    reducers({
        tab: [
            ConfigurationTab.Alerts as ConfigurationTab,
            { persist: true },
            {
                setTab: (_, { tab }) => tab,
            },
        ],
    }),
])

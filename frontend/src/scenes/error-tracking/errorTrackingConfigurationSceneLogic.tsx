import { actions, kea, path, reducers } from 'kea'

import type { errorTrackingConfigurationSceneLogicType } from './errorTrackingConfigurationSceneLogicType'

export enum ErrorTrackingConfigurationTab {
    ALERTS = 'alerts',
    SYMBOL_SETS = 'symbol_sets',
}

export const errorTrackingConfigurationSceneLogic = kea<errorTrackingConfigurationSceneLogicType>([
    path(['scenes', 'error-tracking', 'errorTrackingConfigurationSceneLogic']),

    actions({
        setActiveTab: (tab: ErrorTrackingConfigurationTab) => ({ tab }),
    }),

    reducers({
        activeTab: [
            ErrorTrackingConfigurationTab.ALERTS as ErrorTrackingConfigurationTab,
            {
                setActiveTab: (_, { tab }) => tab,
            },
        ],
    }),
])

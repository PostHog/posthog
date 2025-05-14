import { kea, path, selectors } from 'kea'

import type { sidePanelSdkDoctorLogicType } from './sidePanelSdkDoctorLogicType'

export type SdkHealthStatus = 'healthy' | 'warning' | 'critical'

export const sidePanelSdkDoctorLogic = kea<sidePanelSdkDoctorLogicType>([
    path(['scenes', 'navigation', 'sidepanel', 'sidePanelSdkDoctorLogic']),

    selectors({
        sdkHealth: [
            () => [],
            (): SdkHealthStatus => {
                // Mock implementation for testing
                // Return 'warning' or 'critical' to show the button, 'healthy' to hide it
                return 'healthy'
                return 'warning'
            },
        ],

        needsAttention: [
            (s) => [s.sdkHealth],
            (sdkHealth: SdkHealthStatus): boolean => {
                return sdkHealth === 'warning' || sdkHealth === 'critical'
            },
        ],
    }),
])

import { kea, path, selectors } from 'kea'

import { userLogic } from 'scenes/userLogic'

import type { realtimeNotificationPreferencesLogicType } from './realtimeNotificationPreferencesLogicType'

export type ProjectTriState = 'on' | 'off' | 'partial'

export const realtimeNotificationPreferencesLogic = kea<realtimeNotificationPreferencesLogicType>([
    path(['scenes', 'settings', 'user', 'realtimeNotificationPreferencesLogic']),
    selectors(() => ({
        activeTypes: [
            () => [userLogic.selectors.user],
            (user): string[] => (user?.active_realtime_notification_types ?? []) as string[],
        ],
        disabledMap: [
            () => [userLogic.selectors.user],
            (user): Record<string, Record<string, boolean>> =>
                user?.notification_settings?.realtime_notifications_disabled ?? {},
        ],
        isTypeEnabledForTeam: [
            (s) => [s.disabledMap],
            (disabledMap) =>
                (type: string, teamId: number): boolean =>
                    !disabledMap[type]?.[String(teamId)],
        ],
        projectState: [
            (s) => [s.activeTypes, s.disabledMap],
            (activeTypes, disabledMap) =>
                (teamId: number): ProjectTriState => {
                    if (activeTypes.length === 0) {
                        return 'on'
                    }
                    const enabledFlags = activeTypes.map((type) => !disabledMap[type]?.[String(teamId)])
                    if (enabledFlags.every((v) => v)) {
                        return 'on'
                    }
                    if (enabledFlags.every((v) => !v)) {
                        return 'off'
                    }
                    return 'partial'
                },
        ],
    })),
])

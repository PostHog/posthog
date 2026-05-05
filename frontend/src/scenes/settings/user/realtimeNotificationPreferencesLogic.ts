import { actions, connect, kea, path, reducers, selectors } from 'kea'

import { organizationLogic } from 'scenes/organizationLogic'
import { userLogic } from 'scenes/userLogic'

import { TeamBasicType } from '~/types'

import type { realtimeNotificationPreferencesLogicType } from './realtimeNotificationPreferencesLogicType'

export type ProjectState = 'on' | 'off' | 'partial'

export const realtimeNotificationPreferencesLogic = kea<realtimeNotificationPreferencesLogicType>([
    path(['scenes', 'settings', 'user', 'realtimeNotificationPreferencesLogic']),
    connect({
        values: [userLogic, ['user'], organizationLogic, ['currentOrganization']],
    }),
    actions({
        setProjectExpanded: (teamId: number, expanded: boolean) => ({ teamId, expanded }),
    }),
    reducers({
        expandedOverrides: [
            {} as Record<number, boolean>,
            {
                setProjectExpanded: (state, { teamId, expanded }) => ({ ...state, [teamId]: expanded }),
            },
        ],
    }),
    selectors(() => ({
        teams: [
            (s) => [s.currentOrganization],
            (currentOrganization): TeamBasicType[] => currentOrganization?.teams ?? [],
        ],
        teamIds: [(s) => [s.teams], (teams: TeamBasicType[]): number[] => teams.map((t) => t.id)],
        activeTypes: [
            () => [userLogic.selectors.user],
            (user): string[] => (user?.active_realtime_notification_types ?? []) as string[],
        ],
        disabledMap: [
            () => [userLogic.selectors.user],
            (user): Record<string, Record<string, boolean>> =>
                user?.notification_settings?.realtime_notifications_disabled ?? {},
        ],
        defaultExpanded: [(s) => [s.teams], (teams: TeamBasicType[]): boolean => teams.length <= 3],
        isProjectExpanded: [
            (s) => [s.expandedOverrides, s.defaultExpanded],
            (overrides: Record<number, boolean>, defaultExpanded: boolean) =>
                (teamId: number): boolean =>
                    overrides[teamId] ?? defaultExpanded,
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
                (teamId: number): ProjectState => {
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
        allOn: [
            (s) => [s.teamIds, s.projectState],
            (teamIds: number[], projectState: (teamId: number) => ProjectState): boolean =>
                teamIds.every((teamId) => projectState(teamId) === 'on'),
        ],
        allOff: [
            (s) => [s.teamIds, s.projectState],
            (teamIds: number[], projectState: (teamId: number) => ProjectState): boolean =>
                teamIds.every((teamId) => projectState(teamId) === 'off'),
        ],
    })),
])

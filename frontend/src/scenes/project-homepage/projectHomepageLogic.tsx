import { kea } from 'kea'

import { projectHomepageLogicType } from './projectHomepageLogicType'
import { teamLogic } from 'scenes/teamLogic'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { DEFAULT_DURATION_FILTER } from 'scenes/session-recordings/sessionRecordingsTableLogic'
import { DashboardPlacement, SessionRecordingsResponse, SessionRecordingType } from '~/types'
import api from 'lib/api'
import { toParams } from 'lib/utils'
import { router } from 'kea-router'

export const projectHomepageLogic = kea<projectHomepageLogicType>({
    path: ['scenes', 'project-homepage', 'projectHomepageLogic'],
    connect: {
        values: [teamLogic, ['currentTeamId']],
    },

    actions: {
        loadRecordings: () => true,
        openRecordingModal: (sessionRecordingId: string) => ({ sessionRecordingId }),
        closeRecordingModal: () => true,
    },

    selectors: {
        primaryDashboardId: [() => [teamLogic.selectors.currentTeam], (currentTeam) => currentTeam?.primary_dashboard],
        dashboardLogic: [
            (s) => [s.primaryDashboardId],
            (primaryDashboardId): ReturnType<typeof dashboardLogic.build> | null =>
                dashboardLogic.build(
                    { id: primaryDashboardId ?? undefined, placement: DashboardPlacement.ProjectHomepage },
                    false
                ),
        ],
    },

    reducers: () => ({
        sessionRecordingId: [
            null as null | string,
            {
                openRecordingModal: (_, { sessionRecordingId }) => sessionRecordingId,
                closeRecordingModal: () => null,
            },
        ],
    }),

    loaders: ({ values }) => ({
        recordings: [
            [] as SessionRecordingType[],
            {
                loadRecordings: async (_, breakpoint) => {
                    const paramsDict = {
                        limit: 10,
                        session_recording_duration: DEFAULT_DURATION_FILTER,
                    }
                    const response = (await api.get(
                        `api/projects/${values.currentTeamId}/session_recordings?${toParams(paramsDict)}`
                    )) as SessionRecordingsResponse

                    breakpoint()
                    return response.results
                },
            },
        ],
    }),

    subscriptions: ({ cache }: projectHomepageLogicType) => ({
        dashboardLogic: (logic: ReturnType<typeof dashboardLogic.build>) => {
            cache.unmount?.()
            cache.unmount = logic ? logic.mount() : null
        },
    }),

    events: ({ cache, actions }) => ({
        afterMount: () => {
            cache.unmount?.()
            actions.loadRecordings()
        },
    }),

    actionToUrl: () => ({
        openRecordingModal: ({ sessionRecordingId }) => {
            return [
                router.values.location.pathname,
                { ...router.values.searchParams },
                { ...router.values.hashParams, sessionRecordingId },
            ]
        },
        closeRecordingModal: () => {
            delete router.values.hashParams.sessionRecordingId
            return [router.values.location.pathname, { ...router.values.searchParams }, { ...router.values.hashParams }]
        },
    }),
})

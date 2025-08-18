import { connect, kea, key, path, props } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'

import type { sessionRecordingViewedLogicType } from './sessionRecordingViewedLogicType'

export interface SessionRecordingViewedResult {
    viewed: boolean
    otherViewers: number
}

export type SessionRecordingViewedProps = {
    sessionRecordingId: string
}

export const sessionRecordingViewedLogic = kea<sessionRecordingViewedLogicType>([
    path(['lib', 'components', 'ViewRecordingButton', 'sessionRecordingViewedLogic']),
    key((props: Record<string, unknown>) => props.sessionRecordingId as string),
    props({} as unknown as SessionRecordingViewedProps),
    connect(() => ({
        values: [teamLogic, ['currentTeamId']],
    })),
    loaders(({ props, values }) => ({
        recordingViewed: {
            loadRecordingViewed: async () => {
                if (!props.sessionRecordingId || !values.currentTeamId || props.sessionRecordingId === '') {
                    return { viewed: false, otherViewers: 0 }
                }

                const response = await api.get(
                    `/api/projects/${values.currentTeamId}/session_recordings/${props.sessionRecordingId}/viewed`
                )
                return response as SessionRecordingViewedResult
            },
            userClickedThrough: async () => {
                return { viewed: true, otherViewers: values.recordingViewed?.otherViewers ?? 0 }
            },
        },
    })),
])

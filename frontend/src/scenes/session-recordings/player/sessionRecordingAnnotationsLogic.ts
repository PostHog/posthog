import { afterMount, connect, kea, key, path, props } from 'kea'
import { SessionRecordingLogicProps } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { loaders } from 'kea-loaders'
import { AnnotationScope, RawAnnotationType } from '~/types'
import { teamLogic } from 'scenes/teamLogic'

import type { sessionRecordingAnnotationLogicType } from './sessionRecordingAnnotationsLogicType'
import { now } from 'lib/dayjs'
import api from 'lib/api'

export const sessionRecordingAnnotationLogic = kea<sessionRecordingAnnotationLogicType>([
    path((key) => ['scenes', 'session-recordings', 'player', 'sessionRecordingAnnotationLogic', key]),
    props({} as SessionRecordingLogicProps),
    key((props: SessionRecordingLogicProps) => `${props.playerKey}-${props.sessionRecordingId}`),
    connect({
        values: [teamLogic, ['currentTeam']],
    }),
    loaders(({ props, values }) => ({
        annotations: [
            null as RawAnnotationType[] | null,
            {
                loadAnnotations: async () => {
                    if (!values.currentTeam) {
                        return null
                    }
                    const response = await api.annotations.listBySessionid(props.sessionRecordingId)
                    return (await response.results) as RawAnnotationType[]
                },
                annotate: async ({ content, timestamp }: { content: string; timestamp: number }) => {
                    if (!values.currentTeam) {
                        return null
                    }

                    const response = await api.annotations.annotateRecording({
                        content: content,
                        scope: AnnotationScope.Recording,
                        date_marker: now().toISOString(),
                        recording_timestamp: timestamp,
                        session_id: props.sessionRecordingId,
                    })

                    return [...(values.annotations || []), response] as RawAnnotationType[]
                },
            },
        ],
    })),
    afterMount(({ actions }) => {
        actions.loadAnnotations()
    }),
])

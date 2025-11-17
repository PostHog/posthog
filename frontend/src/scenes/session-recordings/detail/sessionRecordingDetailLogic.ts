import { kea, path, props, selectors } from 'kea'

import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb, SessionRecordingType } from '~/types'

import type { sessionRecordingDetailLogicType } from './sessionRecordingDetailLogicType'

export interface SessionRecordingDetailLogicProps {
    id?: SessionRecordingType['id']
}

export const sessionRecordingDetailLogic = kea<sessionRecordingDetailLogicType>([
    path(['scenes', 'session-recordings', 'detail', 'sessionRecordingDetailLogic']),
    props({} as SessionRecordingDetailLogicProps),
    selectors({
        breadcrumbs: [
            () => [(_, props) => props.id as SessionRecordingType['id']],
            (sessionRecordingId): Breadcrumb[] => [
                {
                    key: Scene.Replay,
                    name: `Replay`,
                    path: urls.replay(),
                    iconType: 'session_replay',
                },
                {
                    key: [Scene.ReplaySingle, sessionRecordingId],
                    name: sessionRecordingId ?? 'Not Found',
                    path: sessionRecordingId ? urls.replaySingle(sessionRecordingId) : undefined,
                    iconType: 'session_replay',
                },
            ],
        ],
    }),
])

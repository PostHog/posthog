import { kea, props, path, selectors } from 'kea'
import { Breadcrumb, SessionRecordingType } from '~/types'
import type { sessionRecordingDetailLogicType } from './sessionRecordingDetailLogicType'
import { urls } from 'scenes/urls'
import { Scene } from 'scenes/sceneTypes'

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
                },
                {
                    key: sessionRecordingId,
                    name: sessionRecordingId ?? 'Not Found',
                    path: sessionRecordingId ? urls.replaySingle(sessionRecordingId) : undefined,
                },
            ],
        ],
    }),
])

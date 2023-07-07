import { kea, props, path, selectors } from 'kea'
import { Breadcrumb, SessionRecordingType } from '~/types'
import type { sessionRecordingDetailLogicType } from './sessionRecordingDetailLogicType'
import { urls } from 'scenes/urls'

export interface SessionRecordingDetailLogicProps {
    id?: SessionRecordingType['id']
}

export const sessionRecordingDetailLogic = kea<sessionRecordingDetailLogicType>([
    path(['scenes', 'session-recordings', 'detail', 'sessionRecordingDetailLogic']),
    props({} as SessionRecordingDetailLogicProps),
    selectors({
        breadcrumbs: [
            () => [(_, props) => props.id],
            (sessionRecordingId): Breadcrumb[] => [
                {
                    name: `Replay`,
                    path: urls.replay(),
                },
                {
                    name: sessionRecordingId ?? 'Not Found',
                    path: sessionRecordingId ? urls.replaySingle(sessionRecordingId) : undefined,
                },
            ],
        ],
    }),
])

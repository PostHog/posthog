import { kea, path, props, selectors } from 'kea'
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

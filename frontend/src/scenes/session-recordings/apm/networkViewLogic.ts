import { afterMount, connect, kea, path, props, selectors } from 'kea'
import { performanceEventDataLogic } from 'scenes/session-recordings/apm/performanceEventDataLogic'
import {
    sessionRecordingDataLogic,
    SessionRecordingDataLogicProps,
} from 'scenes/session-recordings/player/sessionRecordingDataLogic'

import type { networkViewLogicType } from './networkViewLogicType'

export interface NetworkViewLogicProps extends SessionRecordingDataLogicProps {}

export const networkViewLogic = kea<networkViewLogicType>([
    path(['scenes', 'session-recordings', 'apm', 'networkViewLogic']),
    props({} as NetworkViewLogicProps),
    connect((props: NetworkViewLogicProps) => ({
        values: [
            sessionRecordingDataLogic(props),
            ['sessionPlayerData', 'sessionPlayerMetaData', 'snapshotsLoading', 'sessionPlayerMetaDataLoading'],
            performanceEventDataLogic({ key: props.sessionRecordingId, sessionRecordingId: props.sessionRecordingId }),
            ['allPerformanceEvents'],
        ],
        actions: [sessionRecordingDataLogic(props), ['loadSnapshots', 'maybeLoadRecordingMeta']],
    })),
    afterMount(({ actions }) => {
        actions.maybeLoadRecordingMeta()
        actions.loadSnapshots()
    }),
    selectors({
        isLoading: [
            (s) => [s.snapshotsLoading, s.sessionPlayerMetaDataLoading],
            (snapshotsLoading, sessionPlayerMetaDataLoading) => snapshotsLoading || sessionPlayerMetaDataLoading,
        ],
    }),
])

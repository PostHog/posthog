import { actions, afterMount, kea, key, listeners, path, props, reducers } from 'kea'

import api from 'lib/api'

import { SessionRecordingId } from '~/types'

import type { recordingNotFoundLogicType } from './recordingNotFoundLogicType'

export interface RecordingNotFoundLogicProps {
    sessionRecordingId: SessionRecordingId
}

export type MissingReasonType =
    | 'recorded'
    | 'session_missing'
    | 'retention_expired'
    | 'replay_disabled'
    | 'domain_not_allowed'
    | 'url_blocklisted'
    | 'below_min_duration'
    | 'sampled_out'
    | 'triggers_not_matched'
    | 'unknown'

export const recordingNotFoundLogic = kea<recordingNotFoundLogicType>([
    path(['scenes', 'session-recordings', 'components', 'RecordingNotFound', 'recordingNotFoundLogic']),
    props({} as RecordingNotFoundLogicProps),
    key((props) => props.sessionRecordingId),
    actions({
        load: true,
        setIsLoading: (isLoading: boolean) => ({ isLoading }),
        setMissingReason: (missingReason: MissingReasonType) => ({ missingReason }),
    }),
    reducers({
        isLoading: [false, { isLoading: (_, { isLoading }) => isLoading }],
        missingReason: [
            null as MissingReasonType | null,
            { setMissingReason: (_, { missingReason }) => missingReason },
        ],
    }),
    listeners(({ props, actions }) => ({
        load: async () => {
            actions.setIsLoading(true)
            const response = await api.recordings.getMissingReason(props.sessionRecordingId)
            if (response.reason) {
                actions.setMissingReason(response.reason as MissingReasonType)
            }
            actions.setIsLoading(false)
        },
    })),
    afterMount(({ actions }) => {
        actions.load()
    }),
])

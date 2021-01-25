import { SessionsPropertyFilter } from '~/types'

export const SESSIONS_WITH_RECORDINGS_FILTER: SessionsPropertyFilter = {
    type: 'recording',
    key: 'duration',
    value: 0,
    operator: 'gt',
    label: 'Recording duration',
}

export const SESSIONS_WITH_UNSEEN_RECORDINGS: SessionsPropertyFilter = {
    type: 'recording',
    key: 'unseen',
    value: 1,
    label: 'Unseen recordings',
}

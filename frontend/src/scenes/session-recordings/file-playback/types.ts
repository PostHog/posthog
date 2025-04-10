import { eventWithTime } from '@posthog/rrweb-types'

import { PersonType, RecordingSnapshot, SessionRecordingType } from '~/types'

export type ExportedSessionRecordingFileV1 = {
    version: '2022-12-02'
    data: {
        person: PersonType | null
        snapshotsByWindowId: Record<string, eventWithTime[]>
    }
}

export type ExportedSessionRecordingFileV2 = {
    version: '2023-04-28'
    data: {
        id: SessionRecordingType['id']
        person: SessionRecordingType['person']
        snapshots: RecordingSnapshot[]
    }
}

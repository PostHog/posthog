import { eventWithTime } from 'posthog-js/rrweb-types'

import type { ViewportResolution } from '@posthog/replay-shared'

import { PersonType, RecordingSnapshot, SessionRecordingType } from '~/types'

export type ExportedSessionRecordingFileV1 = {
    version: '2022-12-02'
    data: {
        person: PersonType | null
        // Legacy format used UUID strings as keys
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

export type ExportedViewport = ViewportResolution & { timestamp: number }

// Header line of a raw export: `PHREC1\n`, this JSON on one line, then the stored blocks, each as [u32 BE length][snappy block].
export type ExportedSessionRecordingFileRawHeader = {
    version: '2026-11-raw'
    session_id: string
    team_id: number
    distinct_id: string
    start_time: string
    end_time: string
    person: SessionRecordingType['person']
    viewports: ExportedViewport[]
    exported_at: string
    block_count: number
}

export type LoadedSessionRecordingFile = ExportedSessionRecordingFileV2['data'] & {
    viewports?: ExportedViewport[]
}

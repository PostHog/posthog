import api from 'lib/api'
import { Dayjs, dayjs } from 'lib/dayjs'
import { uuid } from 'lib/utils'
import { parseEncodedSnapshots } from 'scenes/session-recordings/player/snapshot-processing/process-all-snapshots'

import {
    RecordingSnapshot,
    SessionRecordingSnapshotParams,
    SessionRecordingSnapshotSource,
    SessionRecordingType,
    SnapshotSourceType,
} from '~/types'

export interface SnapshotLoaderOptions {
    // Define options here
    blob_v2: boolean
    blob_v2_lts: boolean
    accessToken?: string
}

export type WithId<T> = T & {
    id: string
}

export class SnapshotLoader {
    snapshotBySources: Record<string, Promise<WithId<RecordingSnapshot>[]>> = {}

    constructor(
        private sessionId: string,
        private options: SnapshotLoaderOptions,
        private sources: WithId<SessionRecordingSnapshotSource>[],
        private recording: SessionRecordingType
    ) {}

    static build(sessionId: string, options: SnapshotLoaderOptions): Promise<SnapshotLoader> {
        return Promise.all([
            SnapshotLoader.loadSources(sessionId, options),
            SnapshotLoader.loadRecording(sessionId, options),
        ]).then(([sources, recording]) => {
            return new SnapshotLoader(sessionId, options, sources, recording)
        })
    }

    public async loadSnapshotsForTimeRange(start: Dayjs, end: Dayjs): Promise<WithId<RecordingSnapshot>[]> {
        const sources = this.getSourcesForTimeRange(start, end)
        const snapshots = await Promise.all(sources.map((source) => this.loadSnapshotsForSource(source)))
        return snapshots.filter((snapshots) => snapshots != null).flat() as WithId<RecordingSnapshot>[]
    }

    public getSourcesForTimeRange(start: Dayjs, end: Dayjs): WithId<SessionRecordingSnapshotSource>[] {
        return this.sources.filter(
            (source) => dayjs.utc(source.start_timestamp)! <= end && dayjs.utc(source.end_timestamp)! >= start
        )
    }

    private async loadSnapshotsForSource(
        source: WithId<SessionRecordingSnapshotSource>
    ): Promise<WithId<RecordingSnapshot>[] | null> {
        if (!(source.id in this.snapshotBySources)) {
            this.snapshotBySources[source.id] = (async () => {
                let params: SessionRecordingSnapshotParams = this.getParamsForSource(source)
                const headers: Record<string, string> = SnapshotLoader.getHeaders(this.options)
                const response = await api.recordings.getSnapshots(this.sessionId, params, headers).catch((e) => {
                    if (source.source === 'realtime' && e.status === 404) {
                        // Realtime source is not always available, so a 404 is expected
                        return []
                    }
                    throw e
                })

                // sorting is very cheap for already sorted lists
                const parsedSnapshots = (await parseEncodedSnapshots(response, this.sessionId)).sort(
                    (a, b) => a.timestamp - b.timestamp
                )
                return parsedSnapshots.map(createId)
            })()
        }

        return await this.snapshotBySources[source.id]
    }

    private static async loadRecording(
        sessionId: string,
        options: SnapshotLoaderOptions
    ): Promise<SessionRecordingType> {
        const headers: Record<string, string> = this.getHeaders(options)
        return await api.recordings.get(sessionId, {}, headers)
    }

    private static async loadSources(
        sessionId: string,
        options: SnapshotLoaderOptions
    ): Promise<WithId<SessionRecordingSnapshotSource>[]> {
        const headers: Record<string, string> = this.getHeaders(options)
        const blob_v2 = options.blob_v2 || !!options.accessToken
        const blob_v2_lts = options.blob_v2_lts || !!options.accessToken
        const response = await api.recordings.listSnapshotSources(
            sessionId,
            {
                blob_v2,
                blob_v2_lts,
            },
            headers
        )
        if (!response.sources) {
            return []
        }

        const anyBlobV2 = response.sources.some((s) => s.source === SnapshotSourceType.blob_v2)
        if (anyBlobV2) {
            return response.sources.filter((s) => s.source === SnapshotSourceType.blob_v2).map(createId)
        }
        return response.sources.filter((s) => s.source !== SnapshotSourceType.blob_v2).map(createId)
    }

    private static getHeaders(options: SnapshotLoaderOptions): Record<string, string> {
        const headers: Record<string, string> = {}
        if (options.accessToken) {
            headers.Authorization = `Bearer ${options.accessToken}`
        }
        return headers
    }

    private getParamsForSource(source: SessionRecordingSnapshotSource): SessionRecordingSnapshotParams {
        let params: SessionRecordingSnapshotParams
        if (source.source === SnapshotSourceType.blob) {
            if (!source.blob_key) {
                throw new Error('Missing key')
            }
            params = { blob_key: source.blob_key, source: 'blob' }
        } else if (source.source === SnapshotSourceType.realtime) {
            throw new Error('Realtime source not supported')
            // params = { source: 'realtime' }
        } else if (source.source === SnapshotSourceType.blob_v2) {
            if (!source.blob_key) {
                throw new Error('Missing key')
            }
            params = { source: 'blob_v2', blob_key: source.blob_key }
        } else if (source.source === SnapshotSourceType.file) {
            // no need to load a file source, it is already loaded
            throw new Error('File source already loaded')
        } else {
            throw new Error(`Unsupported source: ${source.source}`)
        }
        return params
    }
}

function createId<T>(source: T): WithId<T> {
    return {
        ...source,
        id: uuid(),
    }
}

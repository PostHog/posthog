import { HttpResponse } from 'msw'

import { useAvailableFeatures } from '~/mocks/features'
import { useMocks } from '~/mocks/jest'
import { MockSignature } from '~/mocks/utils'
import { initKeaTests } from '~/test/init'
import { AvailableFeature, RecordingSnapshot, SessionRecordingSnapshotSource } from '~/types'

import recordingEventsJson from '../../__mocks__/recording_events_query'
import { recordingMetaJson } from '../../__mocks__/recording_meta'
import { snapshotsAsJSONLines } from '../../__mocks__/recording_snapshots'
import { sessionRecordingDataCoordinatorLogic } from '../sessionRecordingDataCoordinatorLogic'
import { markLoaded } from '../snapshot-store/test-utils'
import { snapshotDataLogic } from '../snapshotDataLogic'

jest.mock('../snapshot-processing/DecompressionWorkerManager')

export const BLOB_SOURCE_V2: SessionRecordingSnapshotSource = {
    source: 'blob_v2',
    start_timestamp: '2023-08-11T12:03:36.097000Z',
    end_timestamp: '2023-08-11T12:04:52.268000Z',
    blob_key: '0',
}

export const EMPTY_PAGINATED_RESPONSE = {
    results: [],
}

function createSnapshotMockHandler(sources: SessionRecordingSnapshotSource[]): MockSignature {
    return ({ request }) => {
        const sourceParam = new URL(request.url).searchParams.get('source')

        if (sourceParam === 'blob_v2' || sourceParam === 'blob') {
            return new HttpResponse(snapshotsAsJSONLines())
        }

        return [
            200,
            {
                sources,
            },
        ]
    }
}

export interface SessionRecordingTestSetupOptions {
    features?: AvailableFeature[]
    getMocks?: Record<string, MockSignature>
    postMocks?: Record<string, MockSignature>
    patchMocks?: Record<string, MockSignature>
    deleteMocks?: Record<string, MockSignature>
    snapshotSources?: SessionRecordingSnapshotSource[]
    customQueryHandler?: MockSignature
}

function getDefaultMocks(
    snapshotSources: SessionRecordingSnapshotSource[],
    customQueryHandler?: MockSignature
): {
    get: Record<string, MockSignature>
    post: Record<string, MockSignature>
    patch: Record<string, MockSignature>
    delete: Record<string, MockSignature>
} {
    return {
        get: {
            '/api/environments/:team_id/session_recordings/:id/snapshots': createSnapshotMockHandler(snapshotSources),
            '/api/environments/:team_id/session_recordings/:id': recordingMetaJson,
            '/api/projects/:team_id/comments': EMPTY_PAGINATED_RESPONSE,
            '/api/projects/:team/notebooks/recording_comments': EMPTY_PAGINATED_RESPONSE,
        },
        post: {
            '/api/environments/:team_id/query/:kind': customQueryHandler ?? recordingEventsJson,
        },
        patch: {
            '/api/environments/:team_id/session_recordings/:id': { success: true },
        },
        delete: {
            '/api/environments/:team_id/session_recordings/:id': { success: true },
        },
    }
}

/* eslint-disable react-hooks/rules-of-hooks */
export function setupSessionRecordingTest(options: SessionRecordingTestSetupOptions = {}): void {
    const {
        features = [AvailableFeature.RECORDINGS_PERFORMANCE],
        getMocks = {},
        postMocks = {},
        patchMocks = {},
        deleteMocks = {},
        snapshotSources = [BLOB_SOURCE_V2],
        customQueryHandler,
    } = options

    useAvailableFeatures(features)

    const defaults = getDefaultMocks(snapshotSources, customQueryHandler)

    useMocks({
        get: { ...defaults.get, ...getMocks },
        post: { ...defaults.post, ...postMocks },
        patch: { ...defaults.patch, ...patchMocks },
        delete: { ...defaults.delete, ...deleteMocks },
    })

    initKeaTests()
}

export function overrideSessionRecordingMocks(options: Omit<SessionRecordingTestSetupOptions, 'features'> = {}): void {
    const {
        getMocks = {},
        postMocks = {},
        patchMocks = {},
        deleteMocks = {},
        snapshotSources = [BLOB_SOURCE_V2],
        customQueryHandler,
    } = options

    const defaults = getDefaultMocks(snapshotSources, customQueryHandler)

    useMocks({
        get: { ...defaults.get, ...getMocks },
        post: { ...defaults.post, ...postMocks },
        patch: { ...defaults.patch, ...patchMocks },
        delete: { ...defaults.delete, ...deleteMocks },
    })
}

/** One-minute-per-source blob fixtures, for tests that need more than one source to seed. */
export function blobSourcesFrom(startTimestamp: number, blobKeys: string[]): SessionRecordingSnapshotSource[] {
    return blobKeys.map((blobKey, index) => ({
        source: 'blob_v2',
        blob_key: blobKey,
        start_timestamp: new Date(startTimestamp + index * 60000).toISOString(),
        end_timestamp: new Date(startTimestamp + (index + 1) * 60000).toISOString(),
    }))
}

/**
 * Seeds the snapshot store and the processed snapshots segments derive from, bypassing the network
 * loading machinery. Source indices absent from `loaded` stay unfetched, which is how a test puts a
 * seek target in a segment the player can't render yet.
 */
export function seedLoadedSources(
    sessionRecordingId: string,
    sources: SessionRecordingSnapshotSource[],
    loaded: Record<number, RecordingSnapshot[]>
): void {
    const snapshotLogic = snapshotDataLogic({ sessionRecordingId })
    snapshotLogic.actions.loadSnapshotSourcesSuccess(sources)
    const processed: RecordingSnapshot[] = []
    for (const [index, snapshots] of Object.entries(loaded)) {
        markLoaded(snapshotLogic.cache.store, Number(index), snapshots)
        processed.push(...snapshots)
    }
    snapshotLogic.actions.storeUpdated()
    sessionRecordingDataCoordinatorLogic({ sessionRecordingId }).actions.setProcessedSnapshots(processed)
}

export function createDifferentiatedQueryHandler(
    sessionEventsResponse = recordingEventsJson,
    relatedEventsResponse = {
        columns: recordingEventsJson.columns,
        hasMore: false,
        results: [],
        types: recordingEventsJson.types,
    }
): MockSignature {
    return async ({ request }) => {
        const body = (await request.json()) as any
        const query = body.query?.query || ''

        if (query.includes('$session_id =')) {
            return [200, sessionEventsResponse]
        }
        return [200, relatedEventsResponse]
    }
}

export { recordingEventsJson, recordingMetaJson, snapshotsAsJSONLines }

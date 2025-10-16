import { useAvailableFeatures } from '~/mocks/features'
import { useMocks } from '~/mocks/jest'
import { MockSignature } from '~/mocks/utils'
import { initKeaTests } from '~/test/init'
import { AvailableFeature, SessionRecordingSnapshotSource } from '~/types'

import recordingEventsJson from '../../__mocks__/recording_events_query'
import { recordingMetaJson } from '../../__mocks__/recording_meta'
import { snapshotsAsJSONLines } from '../../__mocks__/recording_snapshots'

export const BLOB_SOURCE_V2: SessionRecordingSnapshotSource = {
    source: 'blob_v2',
    start_timestamp: '2023-08-11T12:03:36.097000Z',
    end_timestamp: '2023-08-11T12:04:52.268000Z',
    blob_key: '0',
}

export const BLOB_SOURCE: SessionRecordingSnapshotSource = {
    source: 'blob',
    start_timestamp: '2023-08-11T12:03:36.097000Z',
    end_timestamp: '2023-08-11T12:04:52.268000Z',
    blob_key: '1691755416097-1691755492268',
}

export const EMPTY_PAGINATED_RESPONSE = {
    results: [],
}

function createSnapshotMockHandler(sources: SessionRecordingSnapshotSource[]): MockSignature {
    return async (req, res, ctx) => {
        const sourceParam = req.url.searchParams.get('source')

        if (sourceParam === 'blob_v2' || sourceParam === 'blob') {
            return res(ctx.text(snapshotsAsJSONLines()))
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
            '/api/environments/:team_id/query': customQueryHandler ?? recordingEventsJson,
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

export function createDifferentiatedQueryHandler(
    sessionEventsResponse = recordingEventsJson,
    relatedEventsResponse = {
        columns: recordingEventsJson.columns,
        hasMore: false,
        results: [],
        types: recordingEventsJson.types,
    }
): MockSignature {
    return async (req) => {
        const body = await req.json()
        const query = body.query?.query || ''

        if (query.includes('$session_id =')) {
            return [200, sessionEventsResponse]
        }
        return [200, relatedEventsResponse]
    }
}

export { recordingEventsJson, recordingMetaJson, snapshotsAsJSONLines }

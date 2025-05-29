import { readFileSync } from 'fs'
import { expectLogic } from 'kea-test-utils'
import { api } from 'lib/api.mock'
import { join } from 'path'
import { sessionRecordingDataLogic } from 'scenes/session-recordings/player/sessionRecordingDataLogic'

import { useAvailableFeatures } from '~/mocks/features'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AvailableFeature, SessionRecordingSnapshotSource } from '~/types'

import recordingEventsJson from '../__mocks__/recording_events_query'
import { recordingMetaJson } from '../__mocks__/recording_meta'

const pathForKeyZero = join(__dirname, './__mocks__/blob_key_0.jsonl')
const pathForKeyOne = join(__dirname, './__mocks__/blob_key_1.jsonl')

const readFileContents = (path: string): string => {
    return readFileSync(path, 'utf-8')
}

const keyZero = readFileContents(pathForKeyZero)
const keyOne = readFileContents(pathForKeyOne)

const BLOB_SOURCE: SessionRecordingSnapshotSource = {
    source: 'blob',
    start_timestamp: '2025-05-18T03:46:54.296000Z',
    end_timestamp: '2025-05-18T03:51:54.816000Z',
    blob_key: '1747540014296-1747540314816',
}

const BLOB_V2_SOURCE_ZERO: SessionRecordingSnapshotSource = {
    source: 'blob_v2',
    start_timestamp: '2025-05-18T03:46:53.980000Z',
    end_timestamp: '2025-05-18T03:51:54.709000Z',
    blob_key: '0',
}

const BLOB_V2_SOURCE_ONE: SessionRecordingSnapshotSource = {
    source: 'blob_v2',
    start_timestamp: '2025-05-18T03:51:54.816000Z',
    end_timestamp: '2025-05-18T03:51:54.816000Z',
    blob_key: '1',
}

describe('sessionRecordingDataLogic blobby v2', () => {
    let logic: ReturnType<typeof sessionRecordingDataLogic.build>

    beforeEach(() => {
        useAvailableFeatures([AvailableFeature.RECORDINGS_PERFORMANCE])
        useMocks({
            get: {
                '/api/environments/:team_id/session_recordings/:id/snapshots': async (req, res, ctx) => {
                    // with no sources, returns sources...
                    if (req.url.searchParams.get('source') === 'blob') {
                        throw new Error('not expecting this to be called in this test')
                    } else if (req.url.searchParams.get('source') === 'realtime') {
                        throw new Error('not expecting this to be called in this test')
                    } else if (req.url.searchParams.get('source') === 'blob_v2') {
                        const key = req.url.searchParams.get('blob_key')
                        const start_blob_key = req.url.searchParams.get('start_blob_key')
                        const end_blob_key = req.url.searchParams.get('end_blob_key')

                        if (key === '0') {
                            return res(ctx.text(keyZero))
                        } else if (key === '1') {
                            return res(ctx.text(keyOne))
                        } else if (start_blob_key === '0' && end_blob_key === '1') {
                            // This is the case where we load both blob v2 sources at once
                            return res(ctx.text(`${keyZero}\n${keyOne}`))
                        }
                        throw new Error(`Unexpected blob key: ${key}`)
                    }

                    // to avoid having to mock the flag, this always gets blob v2 sources
                    const sources = [BLOB_V2_SOURCE_ZERO, BLOB_SOURCE, BLOB_V2_SOURCE_ONE]
                    return [
                        200,
                        {
                            sources,
                        },
                    ]
                },
                '/api/environments/:team_id/session_recordings/:id': recordingMetaJson,
            },
            post: {
                '/api/environments/:team_id/query': recordingEventsJson,
            },
            patch: {
                '/api/environments/:team_id/session_recordings/:id': { success: true },
            },
        })
        initKeaTests()
        logic = sessionRecordingDataLogic({
            sessionRecordingId: '2',
            // we don't want to wait for the default real-time polling interval in tests
            realTimePollingIntervalMilliseconds: 10,
            blobV2PollingDisabled: true,
        })
        logic.mount()
        // Most of these tests assume the metadata is being loaded upfront which is the typical case
        logic.actions.loadRecordingMeta()
        jest.spyOn(api, 'get')
        jest.spyOn(api, 'create')
    })

    describe('loading session core', () => {
        it('loads all data', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadSnapshots()
            })
                .toDispatchActions([
                    'loadSnapshots',
                    'loadSnapshotSources',
                    'loadRecordingMetaSuccess',
                    'loadSnapshotSourcesSuccess',
                    // loads the first and second blob v2 source at once
                    'loadSnapshotsForSourceSuccess',
                    'reportUsageIfFullyLoaded',
                ])
                .toFinishAllListeners()

            const actual = logic.values.sessionPlayerData
            actual.snapshotsByWindowId = Object.fromEntries(
                Object.entries(actual.snapshotsByWindowId).map(([windowId, snapshots]) => [
                    windowId,
                    snapshots.map((snapshot) => {
                        const { seen, ...rest } = snapshot as any
                        return rest
                    }),
                ])
            )
            expect(actual).toMatchSnapshot()

            expect(logic.values.snapshotSources).toEqual([
                {
                    blob_key: '0',
                    end_timestamp: '2025-05-18T03:51:54.709000Z',
                    source: 'blob_v2',
                    start_timestamp: '2025-05-18T03:46:53.980000Z',
                },
                {
                    blob_key: '1',
                    end_timestamp: '2025-05-18T03:51:54.816000Z',
                    source: 'blob_v2',
                    start_timestamp: '2025-05-18T03:51:54.816000Z',
                },
            ])
            expect(Object.keys(logic.cache.snapshotsBySource)).toEqual(['blob_v2-0', 'blob_v2-1'])
            expect(logic.cache.snapshotsBySource['blob_v2-0'].snapshots).toHaveLength(11)
            // but blob key 1 is marked empty because its snapshots are on key 0 when loading multi blocks
            expect(logic.cache.snapshotsBySource['blob_v2-1']).toEqual({ snapshots: [] })
        })
    })
})

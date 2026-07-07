import { api } from 'lib/api.mock'

import { readFileSync } from 'fs'
import { expectLogic } from 'kea-test-utils'
import { HttpResponse } from 'msw'
import { join } from 'path'

import { sessionRecordingDataCoordinatorLogic } from 'scenes/session-recordings/player/sessionRecordingDataCoordinatorLogic'

import { SessionRecordingSnapshotSource } from '~/types'

import { setupSessionRecordingTest } from './__mocks__/test-setup'
import { snapshotDataLogic } from './snapshotDataLogic'

const pathForKeyZero = join(__dirname, './__mocks__/blob_key_0.jsonl')
const pathForKeyOne = join(__dirname, './__mocks__/blob_key_1.jsonl')

const readFileContents = (path: string): string => {
    return readFileSync(path, 'utf-8')
}

const keyZero = readFileContents(pathForKeyZero)
const keyOne = readFileContents(pathForKeyOne)

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

describe('sessionRecordingDataCoordinatorLogic blobby v2', () => {
    let logic: ReturnType<typeof sessionRecordingDataCoordinatorLogic.build>
    let snapshotLogic: ReturnType<typeof snapshotDataLogic.build>

    beforeEach(() => {
        setupSessionRecordingTest({
            snapshotSources: [BLOB_V2_SOURCE_ZERO, BLOB_V2_SOURCE_ONE],
            getMocks: {
                '/api/environments/:team_id/session_recordings/:id/snapshots': ({ request }) => {
                    const url = new URL(request.url)
                    if (url.searchParams.get('source') === 'blob') {
                        throw new Error('not expecting this to be called in this test')
                    } else if (url.searchParams.get('source') === 'blob_v2') {
                        const key = url.searchParams.get('blob_key')
                        const start_blob_key = url.searchParams.get('start_blob_key')
                        const end_blob_key = url.searchParams.get('end_blob_key')

                        if (key === '0') {
                            return new HttpResponse(keyZero)
                        } else if (key === '1') {
                            return new HttpResponse(keyOne)
                        } else if (start_blob_key === '2' && end_blob_key === '2') {
                            // a heartbeat blob with no snapshots
                            return new HttpResponse('')
                        } else if (start_blob_key === '0' && end_blob_key === '1') {
                            return new HttpResponse(`${keyZero}\n${keyOne}`)
                        }
                        throw new Error(`Unexpected blob key: ${key}`)
                    }

                    const sources = [BLOB_V2_SOURCE_ZERO, BLOB_V2_SOURCE_ONE]
                    return [
                        200,
                        {
                            sources,
                        },
                    ]
                },
            },
        })
        const props = {
            sessionRecordingId: '2',
            blobV2PollingDisabled: true,
        }
        logic = sessionRecordingDataCoordinatorLogic(props)
        snapshotLogic = snapshotDataLogic(props)
        logic.mount()
        // Most of these tests assume the metadata is being loaded upfront which is the typical case
        logic.actions.loadRecordingMeta()
        jest.spyOn(api, 'get')
        jest.spyOn(api, 'create')
    })

    describe('processing after live source growth', () => {
        it('an empty heartbeat blob does not wipe the processed stream', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadSnapshots()
            })
                .toDispatchActions([snapshotLogic.actionTypes.loadSnapshotsForSourceSuccess, 'setProcessedSnapshots'])
                .toFinishAllListeners()

            const processedBefore = logic.values.snapshots.length
            expect(processedBefore).toBeGreaterThan(0)

            // a live recording appends a blob that contains no snapshots, after earlier raw data was released
            const HEARTBEAT_SOURCE: SessionRecordingSnapshotSource = {
                source: 'blob_v2',
                start_timestamp: '2025-05-18T03:52:00.000000Z',
                end_timestamp: '2025-05-18T03:52:10.000000Z',
                blob_key: '2',
            }
            await expectLogic(logic, () => {
                snapshotLogic.actions.loadSnapshotSourcesSuccess([
                    BLOB_V2_SOURCE_ZERO,
                    BLOB_V2_SOURCE_ONE,
                    HEARTBEAT_SOURCE,
                ])
            })
                .toDispatchActions([snapshotLogic.actionTypes.loadSnapshotsForSourceSuccess, 'setProcessedSnapshots'])
                .toFinishAllListeners()

            expect(logic.values.snapshots.length).toBe(processedBefore)
            expect(snapshotLogic.cache.store.getEntry(2)?.state).toBe('loaded')
        })
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
                    snapshotLogic.actionTypes.loadSnapshotSourcesSuccess,
                    snapshotLogic.actionTypes.loadSnapshotsForSourceSuccess,
                    // loads the first and second blob v2 source at once
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
            // processed snapshots are stored in the cache
            expect(Object.values(logic.cache.processingCache.snapshots).flat()).toHaveLength(11)
        })
    })
})

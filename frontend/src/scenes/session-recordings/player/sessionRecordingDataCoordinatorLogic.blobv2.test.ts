import { api } from 'lib/api.mock'

import { readFileSync } from 'fs'
import { expectLogic } from 'kea-test-utils'
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

describe('sessionRecordingDataCoordinatorLogic blobby v2', () => {
    let logic: ReturnType<typeof sessionRecordingDataCoordinatorLogic.build>
    let snapshotLogic: ReturnType<typeof snapshotDataLogic.build>

    beforeEach(() => {
        setupSessionRecordingTest({
            snapshotSources: [BLOB_V2_SOURCE_ZERO, BLOB_SOURCE, BLOB_V2_SOURCE_ONE],
            getMocks: {
                '/api/environments/:team_id/session_recordings/:id/snapshots': async (req, res, ctx) => {
                    if (req.url.searchParams.get('source') === 'blob') {
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
                            return res(ctx.text(`${keyZero}\n${keyOne}`))
                        }
                        throw new Error(`Unexpected blob key: ${key}`)
                    }

                    const sources = [BLOB_V2_SOURCE_ZERO, BLOB_SOURCE, BLOB_V2_SOURCE_ONE]
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
            expect(Object.keys(logic.values.snapshotsBySources)).toEqual(['blob_v2-0', 'blob_v2-1'])
            expect(logic.values.snapshotsBySources['blob_v2-0'].snapshots).toHaveLength(11)
            // but blob key 1 is marked empty because its snapshots are on key 0 when loading multi blocks
            expect(logic.values.snapshotsBySources['blob_v2-1']).toEqual({
                sourceLoaded: true,
            })
            expect(logic.cache.processingCache['blob_v2-0']).toHaveLength(11)
            expect(logic.cache.processingCache['blob_v2-0']).toEqual(
                logic.values.snapshotsBySources['blob_v2-0'].snapshots
            )
            expect(logic.cache.processingCache['blob_v2-1']).toHaveLength(0)
        })
    })
})

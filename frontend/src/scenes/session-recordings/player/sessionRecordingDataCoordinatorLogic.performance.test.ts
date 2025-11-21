import { readFileSync } from 'fs'
import { expectLogic } from 'kea-test-utils'
import { join } from 'path'

import { uuid } from 'lib/utils'
import { sessionRecordingDataCoordinatorLogic } from 'scenes/session-recordings/player/sessionRecordingDataCoordinatorLogic'

import { setupSessionRecordingTest } from './__mocks__/test-setup'
import { snapshotDataLogic } from './snapshotDataLogic'

const pathForKeyZero = join(__dirname, './__mocks__/perf-snapshot-key0.jsonl')
const pathForKeyOne = join(__dirname, './__mocks__/perf-snapshot-key1.jsonl')

const readFileContents = (path: string): string => {
    return readFileSync(path, 'utf-8')
}

const keyZero = readFileContents(pathForKeyZero)
const keyOne = readFileContents(pathForKeyOne)

jest.setTimeout(120_000)

describe('sessionRecordingDataCoordinatorLogic performance', () => {
    let logic: ReturnType<typeof sessionRecordingDataCoordinatorLogic.build>
    let snapshotLogic: ReturnType<typeof snapshotDataLogic.build>

    beforeEach(() => {
        setupSessionRecordingTest({
            snapshotSources: [
                {
                    source: 'blob_v2',
                    start_timestamp: '2025-05-14T15:37:16.454000Z',
                    end_timestamp: '2025-05-14T15:37:18.379000Z',
                    blob_key: '0',
                },
                {
                    source: 'blob',
                    start_timestamp: '2025-05-14T15:37:16.454000Z',
                    end_timestamp: '2025-05-14T15:37:18.379000Z',
                    blob_key: '1747237036454-1747237038379',
                },
                {
                    source: 'blob_v2',
                    start_timestamp: '2025-05-14T15:37:18.897000Z',
                    end_timestamp: '2025-05-14T15:42:18.378000Z',
                    blob_key: '1',
                },
                {
                    source: 'blob',
                    start_timestamp: '2025-05-14T15:37:18.897000Z',
                    end_timestamp: '2025-05-14T15:42:18.378000Z',
                    blob_key: '1747237038897-1747237338378',
                },
            ],
            getMocks: {
                '/api/environments/:team_id/session_recordings/:id/snapshots': async (req, res, ctx) => {
                    if (req.url.searchParams.get('source') === 'blob_v2') {
                        const key = req.url.searchParams.get('blob_key')
                        const contents = key === '0' ? keyZero : keyOne
                        return res(ctx.text(contents))
                    }

                    return [
                        200,
                        {
                            sources: [
                                {
                                    source: 'blob_v2',
                                    start_timestamp: '2025-05-14T15:37:16.454000Z',
                                    end_timestamp: '2025-05-14T15:37:18.379000Z',
                                    blob_key: '0',
                                },
                                {
                                    source: 'blob',
                                    start_timestamp: '2025-05-14T15:37:16.454000Z',
                                    end_timestamp: '2025-05-14T15:37:18.379000Z',
                                    blob_key: '1747237036454-1747237038379',
                                },
                                {
                                    source: 'blob_v2',
                                    start_timestamp: '2025-05-14T15:37:18.897000Z',
                                    end_timestamp: '2025-05-14T15:42:18.378000Z',
                                    blob_key: '1',
                                },
                                {
                                    source: 'blob',
                                    start_timestamp: '2025-05-14T15:37:18.897000Z',
                                    end_timestamp: '2025-05-14T15:42:18.378000Z',
                                    blob_key: '1747237038897-1747237338378',
                                },
                            ],
                        },
                    ]
                },
            },
        })
    })

    describe('loading snapshots', () => {
        const setupLogic = (): void => {
            const props = {
                sessionRecordingId: uuid(),
                blobV2PollingDisabled: true,
            }
            logic = sessionRecordingDataCoordinatorLogic(props)
            snapshotLogic = snapshotDataLogic(props)
            logic.mount()
            // Most of these tests assume the metadata is being loaded upfront which is the typical case
            logic.actions.loadRecordingMeta()
        }

        it('loads all data', async () => {
            const durations: number[] = []
            const iterations = 10

            // Warm up: initialize DecompressionWorkerManager singleton before timing
            setupLogic()
            await expectLogic(logic, () => {
                logic.actions.loadSnapshots()
            }).toFinishAllListeners()
            logic.unmount()

            for (let i = 0; i < iterations; i++) {
                setupLogic()

                const start = performance.now()

                await expectLogic(logic, () => {
                    logic.actions.loadSnapshots()
                })
                    .toDispatchActions([
                        'loadSnapshots',
                        'loadSnapshotSources',
                        'loadRecordingMetaSuccess',
                        snapshotLogic.actionTypes.loadSnapshotSourcesSuccess,
                        snapshotLogic.actionTypes.loadSnapshotsForSourceSuccess,
                        'reportUsageIfFullyLoaded',
                    ])
                    .toFinishListeners()

                const actual = logic.values.sessionPlayerData
                const snapshotData = actual.snapshotsByWindowId
                expect(Object.keys(snapshotData)).toHaveLength(1)

                const end = performance.now()
                const duration = end - start
                durations.push(duration)

                logic.unmount()
            }

            const averageDuration = durations.reduce((a, b) => a + b, 0) / iterations
            const variance = durations.reduce((a, b) => a + Math.pow(b - averageDuration, 2), 0) / iterations
            const stdDev = Math.sqrt(variance)

            expect(averageDuration).toBeLessThan(130)
            expect(stdDev).toBeLessThan(100)
        })
    })
})

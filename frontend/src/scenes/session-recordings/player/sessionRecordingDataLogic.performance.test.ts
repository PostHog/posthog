import { readFileSync } from 'fs'
import { expectLogic } from 'kea-test-utils'
import { uuid } from 'lib/utils'
import { join } from 'path'
import { sessionRecordingDataLogic } from 'scenes/session-recordings/player/sessionRecordingDataLogic'

import { useAvailableFeatures } from '~/mocks/features'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AvailableFeature } from '~/types'

import recordingEventsJson from '../__mocks__/recording_events_query'
import { recordingMetaJson } from '../__mocks__/recording_meta'
import { snapshotsAsJSONLines } from '../__mocks__/recording_snapshots'

const pathForKeyZero = join(__dirname, './__mocks__/perf-snapshot-key0.jsonl')
const pathForKeyOne = join(__dirname, './__mocks__/perf-snapshot-key1.jsonl')

const readFileContents = (path: string): string => {
    return readFileSync(path, 'utf-8')
}

const keyZero = readFileContents(pathForKeyZero)
const keyOne = readFileContents(pathForKeyOne)

jest.setTimeout(120_000)

describe('sessionRecordingDataLogic performance', () => {
    let logic: ReturnType<typeof sessionRecordingDataLogic.build>

    beforeEach(() => {
        useAvailableFeatures([AvailableFeature.RECORDINGS_PERFORMANCE])
        useMocks({
            get: {
                '/api/environments/:team_id/session_recordings/:id/snapshots': async (req, res, ctx) => {
                    // with no sources, returns sources...
                    if (req.url.searchParams.get('source') === 'blob') {
                        return res(ctx.text(snapshotsAsJSONLines()))
                    } else if (req.url.searchParams.get('source') === 'realtime') {
                        if (req.params.id === 'has-only-empty-realtime') {
                            return res(ctx.json([]))
                        }
                        return res(ctx.text(snapshotsAsJSONLines()))
                    } else if (req.url.searchParams.get('source') === 'blob_v2') {
                        const key = req.url.searchParams.get('blob_key')
                        const contents = key === '0' ? keyZero : keyOne
                        return res(ctx.text(contents))
                    }

                    // with no source requested should return sources
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
    })

    describe('loading snapshots', () => {
        const setupLogic = (): void => {
            logic = sessionRecordingDataLogic({
                sessionRecordingId: uuid(),
                blobV2PollingDisabled: true,
            })
            logic.mount()
            // Most of these tests assume the metadata is being loaded upfront which is the typical case
            logic.actions.loadRecordingMeta()
        }

        it('loads all data', async () => {
            const durations: number[] = []
            const iterations = 10

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
                        'loadSnapshotSourcesSuccess',
                        'loadSnapshotsForSourceSuccess',
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
            // eslint-disable-next-line no-console
            console.log(`Average duration: ${averageDuration}ms`)
            // eslint-disable-next-line no-console
            console.log(`Standard deviation: ${stdDev}ms`)

            expect(averageDuration).toBeLessThan(100)
            expect(stdDev).toBeLessThan(100)
        })
    })
})

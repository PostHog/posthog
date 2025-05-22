import { expectLogic } from 'kea-test-utils'
import { api } from 'lib/api.mock'
import {
    sessionRecordingDataLogic,
} from 'scenes/session-recordings/player/sessionRecordingDataLogic'

import { useAvailableFeatures } from '~/mocks/features'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AvailableFeature } from '~/types'

import recordingEventsJson from '../__mocks__/recording_events_query'
import { recordingMetaJson } from '../__mocks__/recording_meta'
import { snapshotsAsJSONLines } from '../__mocks__/recording_snapshots'

describe('sessionRecordingDataLogic', () => {
    let logic: ReturnType<typeof sessionRecordingDataLogic.build>

    beforeEach(() => {
        useAvailableFeatures([AvailableFeature.RECORDINGS_PERFORMANCE])
        useMocks({
            get: {
                '/api/environments/:team_id/session_recordings/:id/snapshots': async (req, res, ctx) => {
                    console.log(req.url.searchParams)
                    // with no sources, returns sources...
                    if (req.url.searchParams.get('source') === 'blob') {
                        return res(ctx.text(snapshotsAsJSONLines()))
                    } else if (req.url.searchParams.get('source') === 'realtime') {
                        if (req.params.id === 'has-only-empty-realtime') {
                            return res(ctx.json([]))
                        }
                        return res(ctx.text(snapshotsAsJSONLines()))
                    }

                    // with no source requested should return sources
                    console.log('returning sources')
                    return [
                        200,
                        {
                            sources: [
                                    {
                                        "source": "blob_v2",
                                        "start_timestamp": "2025-05-14T15:37:16.454000Z",
                                        "end_timestamp": "2025-05-14T15:37:18.379000Z",
                                        "blob_key": "0"
                                    },
                                    {
                                        "source": "blob",
                                        "start_timestamp": "2025-05-14T15:37:16.454000Z",
                                        "end_timestamp": "2025-05-14T15:37:18.379000Z",
                                        "blob_key": "1747237036454-1747237038379"
                                    },
                                    {
                                        "source": "blob_v2",
                                        "start_timestamp": "2025-05-14T15:37:18.897000Z",
                                        "end_timestamp": "2025-05-14T15:42:18.378000Z",
                                        "blob_key": "1"
                                    },
                                    {
                                        "source": "blob",
                                        "start_timestamp": "2025-05-14T15:37:18.897000Z",
                                        "end_timestamp": "2025-05-14T15:42:18.378000Z",
                                        "blob_key": "1747237038897-1747237338378"
                                    }
                                ]
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
        })
        logic.mount()
        // Most of these tests assume the metadata is being loaded upfront which is the typical case
        logic.actions.loadRecordingMeta()
        jest.spyOn(api, 'get')
        jest.spyOn(api, 'create')
    })

    describe('loading session core', () => {
        it('loads all data', async () => {
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
                .toFinishAllListeners()

            const actual = logic.values.sessionPlayerData
            const snapshotData = actual.snapshotsByWindowId
            expect(snapshotData).toBe({})

            const end = performance.now()

            expect(end - start).toBe(0)
        })

    })

})

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import api from 'lib/api'
import { MOCK_TEAM_ID } from 'lib/api.mock'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import recordingEventsJson from 'scenes/session-recordings/__mocks__/recording_events_query'
import { recordingMetaJson } from 'scenes/session-recordings/__mocks__/recording_meta'
import { snapshotsAsJSONLines } from 'scenes/session-recordings/__mocks__/recording_snapshots'
import { playerSettingsLogic } from 'scenes/session-recordings/player/playerSettingsLogic'
import { sessionRecordingDataLogic } from 'scenes/session-recordings/player/sessionRecordingDataLogic'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { sessionRecordingsPlaylistLogic } from 'scenes/session-recordings/playlist/sessionRecordingsPlaylistLogic'
import { urls } from 'scenes/urls'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { sessionRecordingEventUsageLogic } from '../sessionRecordingEventUsageLogic'
import { makeLogger } from 'scenes/session-recordings/player/rrweb'

describe('sessionRecordingPlayerLogic', () => {
    let logic: ReturnType<typeof sessionRecordingPlayerLogic.build>
    const mockWarn = jest.fn()

    beforeEach(() => {
        console.warn = mockWarn
        mockWarn.mockClear()
        useMocks({
            get: {
                '/api/projects/:team_id/session_recordings/:id/comments/': { results: [] },
                '/api/environments/:team_id/session_recordings/:id/snapshots/': (req, res, ctx) => {
                    // with no sources, returns sources...
                    if (req.url.searchParams.get('source') === 'blob') {
                        return res(ctx.text(snapshotsAsJSONLines()))
                    }
                    // with no source requested should return sources
                    return [
                        200,
                        {
                            sources: [
                                {
                                    source: 'blob',
                                    start_timestamp: '2023-08-11T12:03:36.097000Z',
                                    end_timestamp: '2023-08-11T12:04:52.268000Z',
                                    blob_key: '1691755416097-1691755492268',
                                },
                            ],
                        },
                    ]
                },
                '/api/environments/:team_id/session_recordings/:id': recordingMetaJson,
            },
            delete: {
                '/api/environments/:team_id/session_recordings/:id': { success: true },
            },
            post: {
                '/api/environments/:team_id/query': recordingEventsJson,
            },
        })
        initKeaTests()
        featureFlagLogic.mount()
        logic = sessionRecordingPlayerLogic({ sessionRecordingId: '2', playerKey: 'test' })
        logic.mount()
    })

    describe('core assumptions', () => {
        it('mounts other logics', async () => {
            await expectLogic(logic).toMount([
                sessionRecordingEventUsageLogic,
                sessionRecordingDataLogic({ sessionRecordingId: '2' }),
                playerSettingsLogic,
            ])
        })
    })

    describe('loading session core', () => {
        it('loads metadata only by default', async () => {
            silenceKeaLoadersErrors()

            await expectLogic(logic).toDispatchActionsInAnyOrder([
                sessionRecordingDataLogic({ sessionRecordingId: '2' }).actionTypes.loadRecordingMeta,
                sessionRecordingDataLogic({ sessionRecordingId: '2' }).actionTypes.loadRecordingMetaSuccess,
            ])

            expect(logic.values.sessionPlayerData).toMatchSnapshot()

            await expectLogic(logic).toNotHaveDispatchedActions([
                sessionRecordingDataLogic({ sessionRecordingId: '2' }).actionTypes.loadSnapshotSources,
                sessionRecordingDataLogic({ sessionRecordingId: '2' }).actionTypes.loadSnapshotSourcesSuccess,
            ])
        })

        it('loads metadata and snapshots if autoplay', async () => {
            logic.unmount()
            logic = sessionRecordingPlayerLogic({ sessionRecordingId: '2', playerKey: 'test', autoPlay: true })
            logic.mount()

            silenceKeaLoadersErrors()

            await expectLogic(logic).toDispatchActions([
                sessionRecordingDataLogic({ sessionRecordingId: '2' }).actionTypes.loadRecordingMeta,
                sessionRecordingDataLogic({ sessionRecordingId: '2' }).actionTypes.loadRecordingMetaSuccess,
            ])

            expect(logic.values.sessionPlayerData).toMatchSnapshot()

            await expectLogic(logic).toDispatchActions([
                // once to gather sources
                sessionRecordingDataLogic({ sessionRecordingId: '2' }).actionTypes.loadSnapshotSources,
                // once to load source from that
                sessionRecordingDataLogic({ sessionRecordingId: '2' }).actionTypes.loadSnapshotsForSource,
                sessionRecordingDataLogic({ sessionRecordingId: '2' }).actionTypes.loadSnapshotsForSourceSuccess,
            ])

            expect(logic.values.sessionPlayerData).toMatchSnapshot()

            resumeKeaLoadersErrors()
        })

        it('load snapshot errors and triggers error state', async () => {
            silenceKeaLoadersErrors()
            // Unmount and remount the logic to trigger fetching the data again after the mock change
            logic.unmount()
            logic = sessionRecordingPlayerLogic({
                sessionRecordingId: '2',
                playerKey: 'test',
                autoPlay: true,
            })

            useMocks({
                get: {
                    '/api/environments/:team_id/session_recordings/:id/snapshots': () => [500, { status: 0 }],
                },
            })
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.seekToTime(50) // greater than null buffered time
            })
                .toDispatchActions([
                    'seekToTimestamp',
                    sessionRecordingDataLogic({ sessionRecordingId: '2' }).actionTypes.loadSnapshotSourcesFailure,
                ])
                .toFinishAllListeners()
                .toDispatchActions(['setPlayerError'])

            expect(logic.values).toMatchObject({
                sessionPlayerData: {
                    person: recordingMetaJson.person,
                    snapshotsByWindowId: {},
                    bufferedToTime: 0,
                },
                playerError: 'loadSnapshotSourcesFailure',
            })
            resumeKeaLoadersErrors()
        })
        it('ensures the cache initialization is reset after the player is unmounted', async () => {
            logic.unmount()
            logic = sessionRecordingPlayerLogic({ sessionRecordingId: '2', playerKey: 'test' })
            logic.mount()

            await expectLogic(logic).toDispatchActions([
                sessionRecordingDataLogic({ sessionRecordingId: '2' }).actionTypes.loadRecordingMetaSuccess,
                'initializePlayerFromStart',
            ])
            expect(logic.cache.hasInitialized).toBeTruthy()

            logic.unmount()
            expect(logic.cache.hasInitialized).toBeFalsy()
        })
    })

    describe('delete session recording', () => {
        it('on playlist page', async () => {
            silenceKeaLoadersErrors()
            const listLogic = sessionRecordingsPlaylistLogic({})
            listLogic.mount()
            logic = sessionRecordingPlayerLogic({
                sessionRecordingId: '3',
                playerKey: 'test',
                playlistLogic: listLogic,
            })
            logic.mount()
            jest.spyOn(api, 'delete')

            await expectLogic(logic, () => {
                logic.actions.deleteRecording()
            })
                .toDispatchActions([
                    'deleteRecording',
                    listLogic.actionTypes.loadAllRecordings,
                    listLogic.actionCreators.setSelectedRecordingId(null),
                ])
                .toNotHaveDispatchedActions([
                    sessionRecordingsPlaylistLogic({ updateSearchParams: true }).actionTypes.loadAllRecordings,
                ])

            expect(api.delete).toHaveBeenCalledWith(`api/environments/${MOCK_TEAM_ID}/session_recordings/3`)
            resumeKeaLoadersErrors()
        })

        it('on any other recordings page with a list', async () => {
            silenceKeaLoadersErrors()
            const listLogic = sessionRecordingsPlaylistLogic({ updateSearchParams: true })
            listLogic.mount()
            logic = sessionRecordingPlayerLogic({
                sessionRecordingId: '3',
                playerKey: 'test',
                playlistLogic: listLogic,
            })
            logic.mount()
            jest.spyOn(api, 'delete')

            await expectLogic(logic, () => {
                logic.actions.deleteRecording()
            }).toDispatchActions([
                'deleteRecording',
                listLogic.actionTypes.loadAllRecordings,
                listLogic.actionCreators.setSelectedRecordingId(null),
            ])

            expect(api.delete).toHaveBeenCalledWith(`api/environments/${MOCK_TEAM_ID}/session_recordings/3`)
            resumeKeaLoadersErrors()
        })

        it('on a single recording page', async () => {
            silenceKeaLoadersErrors()
            logic = sessionRecordingPlayerLogic({ sessionRecordingId: '3', playerKey: 'test' })
            logic.mount()
            jest.spyOn(api, 'delete')
            router.actions.push(urls.replaySingle('3'))

            await expectLogic(logic, () => {
                logic.actions.deleteRecording()
            })
                .toDispatchActions(['deleteRecording'])
                .toNotHaveDispatchedActions([
                    sessionRecordingsPlaylistLogic({ updateSearchParams: true }).actionTypes.loadAllRecordings,
                ])
                .toFinishAllListeners()

            expect(router.values.location.pathname).toEqual(urls.replay())

            expect(api.delete).toHaveBeenCalledWith(`api/environments/${MOCK_TEAM_ID}/session_recordings/3`)
            resumeKeaLoadersErrors()
        })

        it('on a single recording modal', async () => {
            silenceKeaLoadersErrors()
            logic = sessionRecordingPlayerLogic({ sessionRecordingId: '3', playerKey: 'test' })
            logic.mount()
            jest.spyOn(api, 'delete')

            await expectLogic(logic, () => {
                logic.actions.deleteRecording()
            })
                .toDispatchActions(['deleteRecording'])
                .toNotHaveDispatchedActions([
                    sessionRecordingsPlaylistLogic({ updateSearchParams: true }).actionTypes.loadAllRecordings,
                ])
                .toFinishAllListeners()

            expect(router.values.location.pathname).toEqual('/')

            expect(api.delete).toHaveBeenCalledWith(`api/environments/${MOCK_TEAM_ID}/session_recordings/3`)
            resumeKeaLoadersErrors()
        })
    })

    describe('matching', () => {
        const listOfMatchingEvents = [
            { uuid: '1', timestamp: '2022-06-01T12:00:00.000Z', session_id: '1', window_id: '1' },
            { uuid: '2', timestamp: '2022-06-01T12:01:00.000Z', session_id: '1', window_id: '1' },
            { uuid: '3', timestamp: '2022-06-01T12:02:00.000Z', session_id: '1', window_id: '1' },
        ]

        it('initialized through props', async () => {
            logic = sessionRecordingPlayerLogic({
                sessionRecordingId: '3',
                playerKey: 'test',
                matchingEventsMatchType: {
                    matchType: 'uuid',
                    eventUUIDs: listOfMatchingEvents.map((event) => event.uuid),
                },
            })
            logic.mount()
            await expectLogic(logic).toMatchValues({
                logicProps: expect.objectContaining({
                    matchingEventsMatchType: {
                        matchType: 'uuid',
                        eventUUIDs: listOfMatchingEvents.map((event) => event.uuid),
                    },
                }),
            })
        })
        it('changes when filter results change', async () => {
            logic = sessionRecordingPlayerLogic({
                sessionRecordingId: '4',
                playerKey: 'test',
                matchingEventsMatchType: {
                    matchType: 'uuid',
                    eventUUIDs: listOfMatchingEvents.map((event) => event.uuid),
                },
            })
            logic.mount()
            await expectLogic(logic).toMatchValues({
                logicProps: expect.objectContaining({
                    matchingEventsMatchType: {
                        matchType: 'uuid',
                        eventUUIDs: listOfMatchingEvents.map((event) => event.uuid),
                    },
                }),
            })
            logic = sessionRecordingPlayerLogic({
                sessionRecordingId: '4',
                playerKey: 'test',
                matchingEventsMatchType: {
                    matchType: 'uuid',
                    eventUUIDs: listOfMatchingEvents.map((event) => event.uuid).slice(0, 1),
                },
            })
            logic.mount()
            await expectLogic(logic).toMatchValues({
                logicProps: expect.objectContaining({
                    matchingEventsMatchType: {
                        matchType: 'uuid',
                        eventUUIDs: listOfMatchingEvents.map((event) => event.uuid).slice(0, 1),
                    },
                }),
            })
        })
    })

    describe('the logger override', () => {
        it('captures replayer warnings', async () => {
            jest.useFakeTimers()

            let warningCounts = 0
            const logger = makeLogger((x) => (warningCounts += x))

            logger.logger.warn('[replayer]', 'test')
            logger.logger.warn('[replayer]', 'test2')
            logger.logger.log('[replayer]', 'test3')

            expect((window as any).__posthog_player_warnings).toEqual([
                ['[replayer]', 'test'],
                ['[replayer]', 'test2'],
            ])
            expect((window as any).__posthog_player_logs).toEqual([['[replayer]', 'test3']])

            jest.runOnlyPendingTimers()
            expect(mockWarn).toHaveBeenCalledWith(
                '[PostHog Replayer] 2 warnings (window.__posthog_player_warnings to safely log them)'
            )
            expect(mockWarn).toHaveBeenCalledWith(
                '[PostHog Replayer] 1 logs (window.__posthog_player_logs to safely log them)'
            )
        })
    })
})

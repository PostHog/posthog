import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import api from 'lib/api'
import { MOCK_TEAM_ID } from 'lib/api.mock'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import posthog from 'posthog-js'
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

    describe('recording viewed summary event', () => {
        describe('play_time_ms tracking', () => {
            it('initializes playingTimeTracking correctly', () => {
                // Test initial state
                expect(logic.values.playingTimeTracking).toEqual({
                    isPlaying: false,
                    isBuffering: false,
                    lastTimestamp: null,
                    watchTime: 0,
                    bufferTime: 0,
                })
            })

            it('sets buffering state with startBuffer', () => {
                logic.actions.startBuffer()

                expect(logic.values.playingTimeTracking.isBuffering).toBe(true)
                expect(logic.values.playingTimeTracking.isPlaying).toBe(false)
                expect(logic.values.playingTimeTracking.lastTimestamp).toBeGreaterThan(0)
            })

            it('demonstrates the issue with endBuffer not tracking buffer time', () => {
                // This test documents the current bug where endBuffer doesn't track buffer time
                logic.actions.startBuffer()

                // Verify we are in buffering state in playingTimeTracking
                expect(logic.values.playingTimeTracking.isBuffering).toBe(true)
                expect(logic.values.playingTimeTracking.lastTimestamp).toBeGreaterThan(0)

                // The separate isBuffering state should also be true
                expect(logic.values.isBuffering).toBe(true)

                // End buffering
                logic.actions.endBuffer()

                // The issue: endBuffer only updates the separate isBuffering state,
                // not the playingTimeTracking state, so buffer time is not accumulated
                expect(logic.values.isBuffering).toBe(false) // This gets updated
                expect(logic.values.playingTimeTracking.isBuffering).toBe(true) // This stays true!
                expect(logic.values.playingTimeTracking.bufferTime).toBe(0) // No time accumulated
            })

            it('sets playing state with setPlay', () => {
                logic.actions.setPlay()

                expect(logic.values.playingTimeTracking.isPlaying).toBe(true)
                expect(logic.values.playingTimeTracking.isBuffering).toBe(false)
                expect(logic.values.playingTimeTracking.lastTimestamp).toBeGreaterThan(0)
            })

            it('accumulates watch time with setPause', () => {
                // Start playing
                logic.actions.setPlay()
                const initialTimestamp = logic.values.playingTimeTracking.lastTimestamp

                // Mock performance.now to advance time
                const originalNow = performance.now
                performance.now = jest.fn().mockReturnValue((initialTimestamp || 0) + 1000)

                logic.actions.setPause()

                expect(logic.values.playingTimeTracking.isPlaying).toBe(false)
                expect(logic.values.playingTimeTracking.watchTime).toBeGreaterThan(0)

                // Restore original performance.now
                performance.now = originalNow
            })

            it('correctly separates play time from buffer time in alternating sequence', () => {
                // This test ensures we don't accumulate playing time while buffering
                // Scenario: 4 x 1-second play blocks with 3 x 1-second buffer blocks between them
                // Expected: 4 seconds play time, 3 seconds buffer time (total 7 seconds, but only 4 should count as play time)

                const originalNow = performance.now
                let currentTime = 1000
                performance.now = jest.fn(() => currentTime)

                // Play block 1 (1 second)
                logic.actions.setPlay()
                currentTime += 1000
                logic.actions.setPause()

                expect(logic.values.playingTimeTracking.watchTime).toBe(1000)
                expect(logic.values.playingTimeTracking.bufferTime).toBe(0)

                // Buffer block 1 (1 second)
                logic.actions.startBuffer()
                currentTime += 1000
                logic.actions.endBuffer() // Note: this doesn't actually accumulate buffer time due to the bug

                expect(logic.values.playingTimeTracking.watchTime).toBe(1000) // Should stay the same
                expect(logic.values.playingTimeTracking.bufferTime).toBe(0) // Bug: doesn't accumulate

                // Play block 2 (1 second)
                logic.actions.setPlay()
                currentTime += 1000
                logic.actions.setPause()

                expect(logic.values.playingTimeTracking.watchTime).toBe(2000)

                // Buffer block 2 (1 second)
                logic.actions.startBuffer()
                currentTime += 1000
                logic.actions.endBuffer()

                expect(logic.values.playingTimeTracking.watchTime).toBe(2000) // Should stay the same

                // Play block 3 (1 second)
                logic.actions.setPlay()
                currentTime += 1000
                logic.actions.setPause()

                expect(logic.values.playingTimeTracking.watchTime).toBe(3000)

                // Buffer block 3 (1 second)
                logic.actions.startBuffer()
                currentTime += 1000
                logic.actions.endBuffer()

                expect(logic.values.playingTimeTracking.watchTime).toBe(3000) // Should stay the same

                // Play block 4 (1 second)
                logic.actions.setPlay()
                currentTime += 1000
                logic.actions.setPause()

                // Final verification: only 4 seconds of play time, not 7 seconds total
                expect(logic.values.playingTimeTracking.watchTime).toBe(4000)
                // expect this to fail due to a bug we need to fix
                expect(logic.values.playingTimeTracking.bufferTime).toBe(3000)

                // Restore original performance.now
                performance.now = originalNow
            })
        })

        describe('recording viewed summary analytics', () => {
            it('captures all required analytics properties on unmount', () => {
                // Mock posthog.capture to spy on the analytics event
                const mockCapture = jest.fn()
                ;(posthog as any).capture = mockCapture

                // Mock performance.now to simulate time passing
                const originalNow = performance.now
                let currentTime = 1000
                performance.now = jest.fn(() => currentTime)

                // Simulate user interaction that generates play time
                logic.actions.setPlay()
                currentTime += 1000 // Advance time by 1 second
                logic.actions.setPause()

                logic.actions.incrementClickCount()
                logic.actions.incrementWarningCount(2)
                logic.actions.incrementErrorCount()

                // Unmount to trigger the analytics event
                logic.unmount()

                expect(mockCapture).toHaveBeenCalledWith(
                    'recording viewed summary',
                    expect.objectContaining({
                        viewed_time_ms: expect.any(Number),
                        play_time_ms: expect.any(Number),
                        buffer_time_ms: expect.any(Number),
                        rrweb_warning_count: 2,
                        error_count_during_recording_playback: 1,
                        engagement_score: 1,
                    })
                )

                // Verify play_time_ms is greater than 0
                const capturedArgs = mockCapture.mock.calls[0][1]
                expect(capturedArgs.play_time_ms).toBeGreaterThan(0)
                expect(capturedArgs).toHaveProperty('recording_duration_ms')
                expect(capturedArgs).toHaveProperty('recording_age_ms')

                // Restore original performance.now
                performance.now = originalNow
            })

            it('captures "no playtime summary" event when play_time_ms is 0', async () => {
                // Mock posthog.capture to spy on the analytics event
                const mockCapture = jest.fn()
                ;(posthog as any).capture = mockCapture

                // Don't play the recording, just unmount
                logic.unmount()

                expect(mockCapture).toHaveBeenCalledWith(
                    'recording viewed with no playtime summary',
                    expect.objectContaining({
                        viewed_time_ms: expect.any(Number),
                        play_time_ms: 0,
                        buffer_time_ms: 0,
                        engagement_score: 0,
                    })
                )
            })

            it('calculates engagement score based on click count', async () => {
                const mockCapture = jest.fn()
                ;(posthog as any).capture = mockCapture

                // Simulate multiple clicks
                logic.actions.incrementClickCount()
                logic.actions.incrementClickCount()
                logic.actions.incrementClickCount()

                logic.unmount()

                expect(mockCapture).toHaveBeenCalledWith(
                    'recording viewed with no playtime summary',
                    expect.objectContaining({
                        engagement_score: 3,
                    })
                )
            })
        })
    })
})

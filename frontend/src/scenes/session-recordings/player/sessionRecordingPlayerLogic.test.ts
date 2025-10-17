import { MOCK_TEAM_ID } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import api from 'lib/api'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { removeProjectIdIfPresent } from 'lib/utils/router-utils'
import { playerSettingsLogic } from 'scenes/session-recordings/player/playerSettingsLogic'
import { makeLogger } from 'scenes/session-recordings/player/rrweb'
import { sessionRecordingDataCoordinatorLogic } from 'scenes/session-recordings/player/sessionRecordingDataCoordinatorLogic'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { sessionRecordingsPlaylistLogic } from 'scenes/session-recordings/playlist/sessionRecordingsPlaylistLogic'
import { urls } from 'scenes/urls'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'

import { sessionRecordingEventUsageLogic } from '../sessionRecordingEventUsageLogic'
import {
    BLOB_SOURCE,
    overrideSessionRecordingMocks,
    recordingMetaJson,
    setupSessionRecordingTest,
} from './__mocks__/test-setup'
import { snapshotDataLogic } from './snapshotDataLogic'

describe('sessionRecordingPlayerLogic', () => {
    let logic: ReturnType<typeof sessionRecordingPlayerLogic.build>
    const mockWarn = jest.fn()

    beforeEach(() => {
        console.warn = mockWarn
        mockWarn.mockClear()
        setupSessionRecordingTest({
            snapshotSources: [BLOB_SOURCE],
        })
        featureFlagLogic.mount()
        logic = sessionRecordingPlayerLogic({ sessionRecordingId: '2', playerKey: 'test' })
        logic.mount()
    })

    describe('core assumptions', () => {
        it('mounts other logics', async () => {
            await expectLogic(logic).toMount([
                sessionRecordingEventUsageLogic,
                sessionRecordingDataCoordinatorLogic({ sessionRecordingId: '2' }),
                playerSettingsLogic,
            ])
        })
    })

    describe('loading session core', () => {
        it('loads metadata and snapshots by default', async () => {
            silenceKeaLoadersErrors()

            await expectLogic(logic).toDispatchActionsInAnyOrder([
                sessionRecordingDataCoordinatorLogic({ sessionRecordingId: '2' }).actionTypes.loadRecordingMeta,
                sessionRecordingDataCoordinatorLogic({ sessionRecordingId: '2' }).actionTypes.loadRecordingMetaSuccess,
            ])

            expect(logic.values.sessionPlayerData).toMatchSnapshot()

            await expectLogic(logic).toDispatchActions([
                snapshotDataLogic({ sessionRecordingId: '2' }).actionTypes.loadSnapshotSources,
                snapshotDataLogic({ sessionRecordingId: '2' }).actionTypes.loadSnapshotSourcesSuccess,
            ])
        })

        it('loads metadata and snapshots if autoplay', async () => {
            logic.unmount()
            logic = sessionRecordingPlayerLogic({ sessionRecordingId: '2', playerKey: 'test', autoPlay: true })
            logic.mount()

            silenceKeaLoadersErrors()

            await expectLogic(logic).toDispatchActions([
                sessionRecordingDataCoordinatorLogic({ sessionRecordingId: '2' }).actionTypes.loadRecordingData,
                sessionRecordingDataCoordinatorLogic({ sessionRecordingId: '2' }).actionTypes.loadRecordingMeta,
                sessionRecordingDataCoordinatorLogic({ sessionRecordingId: '2' }).actionTypes.loadRecordingMetaSuccess,
                snapshotDataLogic({ sessionRecordingId: '2' }).actionTypes.loadSnapshotSources,
                logic.actionTypes.setPlay,
                snapshotDataLogic({ sessionRecordingId: '2' }).actionTypes.loadSnapshotSourcesSuccess,
            ])

            expect(logic.values.sessionPlayerData).toMatchSnapshot()

            resumeKeaLoadersErrors()
        })

        it('marks as viewed once playing', async () => {
            logic.unmount()
            logic = sessionRecordingPlayerLogic({ sessionRecordingId: '2', playerKey: 'test', autoPlay: true })
            logic.mount()

            silenceKeaLoadersErrors()

            await expectLogic(logic).toDispatchActions([logic.actionTypes.setPlay, logic.actionTypes.markViewed])

            resumeKeaLoadersErrors()
        })

        it('load snapshot errors and triggers error state', async () => {
            logic.unmount()
            overrideSessionRecordingMocks({
                getMocks: {
                    '/api/environments/:team_id/session_recordings/:id/snapshots': () => [500, { status: 0 }],
                    '/api/projects/:team_id/session_recordings/:id/snapshots': () => [500, { status: 0 }],
                },
            })
            logic = sessionRecordingPlayerLogic({
                sessionRecordingId: '2',
                playerKey: 'test',
                autoPlay: true,
            })

            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.seekToTime(50) // greater than null buffered time
            })
                .toDispatchActions([
                    'seekToTimestamp',
                    snapshotDataLogic({ sessionRecordingId: '2' }).actionTypes.loadSnapshotSourcesFailure,
                ])
                .toFinishAllListeners()
                .toDispatchActions(['setPlayerError'])
                .toNotHaveDispatchedActions(['markViewed'])

            expect(logic.values).toMatchObject({
                sessionPlayerData: {
                    person: recordingMetaJson.person,
                    snapshotsByWindowId: {},
                    bufferedToTime: 0,
                },
                playerError: 'loadSnapshotSourcesFailure',
            })
        })

        it('ensures the cache initialization is reset after the player is unmounted', async () => {
            logic.unmount()
            logic = sessionRecordingPlayerLogic({ sessionRecordingId: '2', playerKey: 'test' })
            logic.mount()

            await expectLogic(logic).toDispatchActions([
                sessionRecordingDataCoordinatorLogic({ sessionRecordingId: '2' }).actionTypes.loadRecordingMetaSuccess,
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

            expect(removeProjectIdIfPresent(router.values.location.pathname)).toEqual(urls.replay())

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

            expect(router.values.location.pathname).toEqual('/project/997')

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
            beforeEach(() => {
                jest.useFakeTimers({
                    now: new Date('2024-02-07T00:00:01.123Z'),
                })
            })

            it('initializes playingTimeTracking correctly', () => {
                expect(logic.values.playingTimeTracking).toEqual({
                    state: 'unknown',
                    lastTimestamp: null,
                    watchTime: 0,
                    bufferTime: 0,
                })
            })

            it('sets buffering state with startBuffer', () => {
                expect(logic.values.playingTimeTracking.lastTimestamp).toBeNull()

                logic.actions.startBuffer()

                expect(logic.values.playingTimeTracking.state).toBe('buffering')
                expect(logic.values.playingTimeTracking.lastTimestamp).not.toBeNull()
            })

            it('correctly tracks buffer time', () => {
                logic.actions.startBuffer()

                expect(logic.values.playingTimeTracking.state).toBe('buffering')
                expect(logic.values.playingTimeTracking.lastTimestamp).toBe(0)

                jest.advanceTimersByTime(1500)
                logic.actions.endBuffer()

                expect(logic.values.playingTimeTracking.state).toBe('buffering')
                expect(logic.values.playingTimeTracking.bufferTime).toBe(1500)
                expect(logic.values.playingTimeTracking.watchTime).toBe(0)
            })

            it('sets playing state with setPlay', () => {
                logic.actions.setPlay()

                expect(logic.values.playingTimeTracking.state).toBe('playing')
                expect(logic.values.playingTimeTracking.lastTimestamp).toBe(0)
            })

            it('accumulates watch time with setPause', () => {
                logic.actions.setPlay()

                jest.advanceTimersByTime(1000)
                logic.actions.setPause()

                expect(logic.values.playingTimeTracking.state).toBe('paused')
                expect(logic.values.playingTimeTracking.watchTime).toBe(1000)
            })

            it('correctly separates play time from buffer time in alternating sequence', () => {
                // This test ensures we don't accumulate playing time while buffering
                // Scenario: 4 x 1-second play blocks with 3 x 1-second buffer blocks between them
                // Expected: 4 seconds play time, 3 seconds buffer time (total 7 seconds, but only 4 should count as play time)

                // Play block 1 (1 second)
                logic.actions.setPlay()
                jest.advanceTimersByTime(1000)
                logic.actions.setPause()

                expect(logic.values.playingTimeTracking.watchTime).toBe(1000)
                expect(logic.values.playingTimeTracking.bufferTime).toBe(0)

                logic.actions.startBuffer()
                jest.advanceTimersByTime(1000)
                logic.actions.endBuffer()

                expect(logic.values.playingTimeTracking.watchTime).toBe(1000)
                expect(logic.values.playingTimeTracking.bufferTime).toBe(1000)

                logic.actions.setPlay()
                jest.advanceTimersByTime(1000)
                logic.actions.setPause()

                expect(logic.values.playingTimeTracking.watchTime).toBe(2000)

                logic.actions.startBuffer()
                jest.advanceTimersByTime(1000)
                logic.actions.endBuffer()

                expect(logic.values.playingTimeTracking.watchTime).toBe(2000)
                expect(logic.values.playingTimeTracking.bufferTime).toBe(2000)

                logic.actions.setPlay()
                jest.advanceTimersByTime(1000)
                logic.actions.setPause()

                expect(logic.values.playingTimeTracking.watchTime).toBe(3000)

                logic.actions.startBuffer()
                jest.advanceTimersByTime(1000)
                logic.actions.endBuffer()

                expect(logic.values.playingTimeTracking.watchTime).toBe(3000)
                expect(logic.values.playingTimeTracking.bufferTime).toBe(3000)

                logic.actions.setPlay()
                jest.advanceTimersByTime(1000)
                logic.actions.setPause()

                // Final verification: only 4 seconds of play time, not 7 seconds total
                expect(logic.values.playingTimeTracking.watchTime).toBe(4000)
                // Should correctly track 3 seconds of buffer time
                expect(logic.values.playingTimeTracking.bufferTime).toBe(3000)
            })

            it('handles repeated endBuffer calls without losing time', () => {
                // This test simulates the real-world scenario where endBuffer gets called multiple times
                logic.actions.startBuffer()
                expect(logic.values.playingTimeTracking.state).toBe('buffering')

                jest.advanceTimersByTime(1000)
                logic.actions.endBuffer()

                expect(logic.values.playingTimeTracking.state).toBe('buffering')
                expect(logic.values.playingTimeTracking.bufferTime).toBe(1000)

                logic.actions.endBuffer()

                // This should NOT reset the buffer time to 0
                expect(logic.values.playingTimeTracking.bufferTime).toBe(1000)

                logic.actions.endBuffer()
                logic.actions.endBuffer()
                logic.actions.endBuffer()

                // Buffer time should remain stable
                expect(logic.values.playingTimeTracking.bufferTime).toBe(1000)
            })
        })

        describe('recording viewed summary analytics', () => {
            it('captures all required analytics properties on unmount', () => {
                // Mock posthog.capture to spy on the analytics event
                const mockCapture = jest.fn()
                ;(posthog as any).capture = mockCapture

                // Use fake timers for this test
                jest.useFakeTimers()

                // Simulate user interaction that generates play time
                logic.actions.setPlay()
                jest.advanceTimersByTime(1000) // Advance time by 1 second
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
                        play_time_ms: 1000,
                        buffer_time_ms: 0,
                        rrweb_warning_count: 2,
                        error_count_during_recording_playback: 1,
                        engagement_score: 1,
                        recording_duration_ms: 0,
                        recording_age_ms: undefined,
                    })
                )
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

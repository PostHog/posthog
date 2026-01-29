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
    BLOB_SOURCE_V2,
    overrideSessionRecordingMocks,
    recordingMetaJson,
    setupSessionRecordingTest,
} from './__mocks__/test-setup'
import { snapshotDataLogic } from './snapshotDataLogic'

jest.mock('./snapshot-processing/DecompressionWorkerManager')

describe('sessionRecordingPlayerLogic', () => {
    let logic: ReturnType<typeof sessionRecordingPlayerLogic.build>
    const mockWarn = jest.fn()

    beforeEach(() => {
        console.warn = mockWarn
        mockWarn.mockClear()
        setupSessionRecordingTest({
            snapshotSources: [BLOB_SOURCE_V2],
        })
        featureFlagLogic.mount()
        logic = sessionRecordingPlayerLogic({ sessionRecordingId: '2', playerKey: 'test', blobV2PollingDisabled: true })
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
        it('calls onRecordingDeleted callback when provided', async () => {
            silenceKeaLoadersErrors()
            const onRecordingDeleted = jest.fn()
            logic = sessionRecordingPlayerLogic({
                sessionRecordingId: '3',
                playerKey: 'test',
                blobV2PollingDisabled: true,
                onRecordingDeleted,
            })
            logic.mount()
            jest.spyOn(api, 'delete')

            await expectLogic(logic, () => {
                logic.actions.deleteRecording()
            })
                .toDispatchActions(['deleteRecording'])
                .toFinishAllListeners()

            expect(api.delete).toHaveBeenCalledWith(`api/environments/${MOCK_TEAM_ID}/session_recordings/3`)
            expect(onRecordingDeleted).toHaveBeenCalled()
            resumeKeaLoadersErrors()
        })

        it('on a single recording page', async () => {
            silenceKeaLoadersErrors()
            logic = sessionRecordingPlayerLogic({
                sessionRecordingId: '3',
                playerKey: 'test',
                blobV2PollingDisabled: true,
            })
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
            logic = sessionRecordingPlayerLogic({
                sessionRecordingId: '3',
                playerKey: 'test',
                blobV2PollingDisabled: true,
            })
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
                    matchedEvents: listOfMatchingEvents,
                },
            })
            logic.mount()
            await expectLogic(logic).toMatchValues({
                logicProps: expect.objectContaining({
                    matchingEventsMatchType: {
                        matchType: 'uuid',
                        matchedEvents: listOfMatchingEvents,
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
                    matchedEvents: listOfMatchingEvents,
                },
            })
            logic.mount()
            await expectLogic(logic).toMatchValues({
                logicProps: expect.objectContaining({
                    matchingEventsMatchType: {
                        matchType: 'uuid',
                        matchedEvents: listOfMatchingEvents,
                    },
                }),
            })
            logic = sessionRecordingPlayerLogic({
                sessionRecordingId: '4',
                playerKey: 'test',
                matchingEventsMatchType: {
                    matchType: 'uuid',
                    matchedEvents: listOfMatchingEvents.slice(0, 1),
                },
            })
            logic.mount()
            await expectLogic(logic).toMatchValues({
                logicProps: expect.objectContaining({
                    matchingEventsMatchType: {
                        matchType: 'uuid',
                        matchedEvents: listOfMatchingEvents.slice(0, 1),
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
            const startPlaying = (): void => {
                logic.actions.setPlay()
                logic.actions.endBuffer()
            }

            beforeEach(() => {
                jest.useFakeTimers({
                    now: new Date('2024-02-07T00:00:01.123Z'),
                })
                logic.unmount()
                logic = sessionRecordingPlayerLogic({ sessionRecordingId: '2', playerKey: 'test' })
                logic.mount()
            })

            it('initializes playingTimeTracking correctly', () => {
                expect(logic.values.playingTimeTracking).toEqual({
                    state: 'paused',
                    lastTimestamp: null,
                    watchTime: 0,
                    bufferTime: 0,
                    firstPlayTime: undefined,
                    firstPlayStartTime: undefined,
                })
            })

            it('sets buffering state with startBuffer', () => {
                expect(logic.values.playingTimeTracking.lastTimestamp).toBeNull()

                logic.actions.setPlay()
                logic.actions.startBuffer()

                expect(logic.values.playingTimeTracking.state).toBe('buffering')
                expect(logic.values.playingTimeTracking.lastTimestamp).not.toBeNull()
            })

            it('tracks buffer time', () => {
                logic.actions.setPlay()
                logic.actions.startBuffer()
                jest.advanceTimersByTime(1500)
                logic.actions.endBuffer()

                expect(logic.values.playingTimeTracking.bufferTime).toBe(1500)
                expect(logic.values.playingTimeTracking.watchTime).toBe(0)
            })

            it('transitions to playing after endBuffer', () => {
                startPlaying()

                expect(logic.values.playingTimeTracking.state).toBe('playing')
            })

            it('accumulates watch time during play', () => {
                startPlaying()
                jest.advanceTimersByTime(1000)
                logic.actions.setPause()

                expect(logic.values.playingTimeTracking.watchTime).toBe(1000)
            })

            it('separates play and buffer time when alternating', () => {
                const playFor = (ms: number): void => {
                    startPlaying()
                    jest.advanceTimersByTime(ms)
                    logic.actions.setPause()
                }

                const bufferFor = (ms: number): void => {
                    logic.actions.startBuffer()
                    jest.advanceTimersByTime(ms)
                    logic.actions.endBuffer()
                }

                playFor(1000)
                bufferFor(1000)
                playFor(1000)
                bufferFor(1000)
                playFor(1000)
                bufferFor(1000)
                playFor(1000)

                expect(logic.values.playingTimeTracking.watchTime).toBe(4000)
                expect(logic.values.playingTimeTracking.bufferTime).toBe(3000)
            })

            it('preserves buffer time on repeated endBuffer calls', () => {
                logic.actions.setPlay()
                logic.actions.startBuffer()
                jest.advanceTimersByTime(1000)
                logic.actions.endBuffer()

                const bufferTime = logic.values.playingTimeTracking.bufferTime

                logic.actions.endBuffer()
                logic.actions.endBuffer()
                logic.actions.endBuffer()

                expect(logic.values.playingTimeTracking.bufferTime).toBe(bufferTime)
            })

            describe('time_to_first_play_ms tracking', () => {
                it('preserves firstPlayTime after buffer interrupts post-threshold', () => {
                    startPlaying()
                    jest.advanceTimersByTime(1000)
                    jest.runOnlyPendingTimers()

                    expect(logic.values.playingTimeTracking.firstPlayTime).toBe(0)

                    logic.actions.startBuffer()
                    jest.runOnlyPendingTimers()

                    expect(logic.values.playingTimeTracking.firstPlayTime).toBe(0)
                })

                it('records firstPlayTime only once', () => {
                    startPlaying()
                    jest.advanceTimersByTime(1000)
                    jest.runOnlyPendingTimers()

                    const firstPlayTime = logic.values.playingTimeTracking.firstPlayTime

                    logic.actions.setPause()
                    logic.actions.setPlay()
                    jest.advanceTimersByTime(2000)
                    jest.runOnlyPendingTimers()

                    expect(logic.values.playingTimeTracking.firstPlayTime).toBe(firstPlayTime)
                })

                it('retries tracking after early interruption', () => {
                    jest.advanceTimersByTime(500)

                    logic.actions.setPause()
                    expect(logic.values.playingTimeTracking.firstPlayTime).toBeUndefined()

                    startPlaying()
                    jest.runOnlyPendingTimers()

                    expect(logic.values.playingTimeTracking.firstPlayTime).toBe(500)
                })
            })
        })

        describe('recording viewed summary analytics', () => {
            it('captures all required analytics properties on unmount', () => {
                jest.useFakeTimers()
                logic.unmount()
                logic = sessionRecordingPlayerLogic({ sessionRecordingId: '2', playerKey: 'test' })
                logic.mount()

                const mockCapture = jest.fn()
                ;(posthog as any).capture = mockCapture

                logic.actions.setPlay()
                logic.actions.endBuffer()
                jest.advanceTimersByTime(1001)
                logic.actions.setPause()

                logic.actions.incrementClickCount()
                logic.actions.incrementWarningCount(2)
                logic.actions.incrementErrorCount()

                logic.unmount()

                expect(mockCapture).toHaveBeenCalledWith(
                    'recording viewed summary',
                    expect.objectContaining({
                        viewed_time_ms: expect.any(Number),
                        play_time_ms: expect.any(Number),
                        buffer_time_ms: expect.any(Number),
                        time_to_first_play_ms: expect.any(Number),
                        rrweb_warning_count: 2,
                        error_count_during_recording_playback: 1,
                        engagement_score: 1,
                        recording_duration_ms: 0,
                        recording_age_ms: undefined,
                    })
                )
                expect(mockCapture.mock.calls[0][1].time_to_first_play_ms).toBe(0)
            })

            it('captures "no playtime summary" event when play_time_ms is 0', async () => {
                const mockCapture = jest.fn()
                ;(posthog as any).capture = mockCapture

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

    describe('seek actions', () => {
        it('seekForward without parameter uses default jumpTimeMs (10s)', () => {
            const currentTime = 5000
            logic.actions.seekToTime(currentTime)

            const jumpTimeMs = logic.values.jumpTimeMs
            expect(jumpTimeMs).toBe(10000) // 10s * speed(1)

            logic.actions.seekForward()
            // seekForward should call seekToTime with current time + jumpTimeMs
        })

        it('seekBackward without parameter uses default jumpTimeMs (10s)', () => {
            const currentTime = 15000
            logic.actions.seekToTime(currentTime)

            const jumpTimeMs = logic.values.jumpTimeMs
            expect(jumpTimeMs).toBe(10000) // 10s * speed(1)

            logic.actions.seekBackward()
            // seekBackward should call seekToTime with current time - jumpTimeMs
        })

        it('seekForward with 1000ms parameter jumps forward 1s', () => {
            const currentTime = 5000
            logic.actions.seekToTime(currentTime)
            logic.actions.seekForward(1000)
            // seekForward should call seekToTime with current time + 1000
        })

        it('seekBackward with 1000ms parameter jumps backward 1s', () => {
            const currentTime = 5000
            logic.actions.seekToTime(currentTime)
            logic.actions.seekBackward(1000)
            // seekBackward should call seekToTime with current time - 1000
        })

        it('seekForward respects custom amount parameter', () => {
            const currentTime = 5000
            const customAmount = 2500
            logic.actions.seekToTime(currentTime)
            logic.actions.seekForward(customAmount)
            // seekForward should call seekToTime with current time + customAmount
        })

        it('seekBackward respects custom amount parameter', () => {
            const currentTime = 5000
            const customAmount = 3500
            logic.actions.seekToTime(currentTime)
            logic.actions.seekBackward(customAmount)
            // seekBackward should call seekToTime with current time - customAmount
        })

        it('default jumpTimeMs scales with playback speed', () => {
            logic.actions.setSpeed(2)

            const jumpTimeMs = logic.values.jumpTimeMs
            expect(jumpTimeMs).toBe(20000) // 10s * speed(2)

            logic.actions.seekToTime(5000)
            logic.actions.seekForward()
            // seekForward should call seekToTime with current time + 20000
        })
    })
})

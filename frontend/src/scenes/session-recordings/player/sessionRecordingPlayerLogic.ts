import { actions, connect, events, kea, key, listeners, path, props, propsChanged, reducers, selectors } from 'kea'
import { windowValues } from 'kea-window-values'
import type { sessionRecordingPlayerLogicType } from './sessionRecordingPlayerLogicType'
import { Replayer } from 'rrweb'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import {
    AvailableFeature,
    MatchedRecording,
    PlayerPosition,
    RecordingSegment,
    SessionPlayerData,
    SessionPlayerState,
    SessionRecordingId,
    SessionRecordingType,
} from '~/types'
import { getBreakpoint } from 'lib/utils/responsiveUtils'
import { sessionRecordingDataLogic } from 'scenes/session-recordings/player/sessionRecordingDataLogic'
import {
    comparePlayerPositions,
    getPlayerPositionFromPlayerTime,
    getPlayerTimeFromPlayerPosition,
    getSegmentFromPlayerPosition,
} from './playerUtils'
import { playerSettingsLogic } from './playerSettingsLogic'
import { sharedListLogic } from 'scenes/session-recordings/player/list/sharedListLogic'
import equal from 'fast-deep-equal'
import { downloadFile, fromParamsGivenUrl } from 'lib/utils'
import { lemonToast } from '@posthog/lemon-ui'
import { delay } from 'kea-test-utils'
import { ExportedSessionRecordingFile } from '../file-playback/sessionRecodingFilePlaybackLogic'
import { userLogic } from 'scenes/userLogic'
import { openBillingPopupModal } from 'scenes/billing/v2/BillingPopup'

export const PLAYBACK_SPEEDS = [0.5, 1, 2, 3, 4, 8, 16]
export const ONE_FRAME_MS = 100 // We don't really have frames but this feels granular enough

export interface Player {
    replayer: Replayer
    windowId: string
}

export interface SessionRecordingPlayerLogicProps {
    sessionRecordingId: SessionRecordingId
    sessionRecordingData?: SessionPlayerData
    playlistShortId?: string
    playerKey: string
    matching?: MatchedRecording[]
    recordingStartTime?: string
}

export const sessionRecordingPlayerLogic = kea<sessionRecordingPlayerLogicType>([
    path((key) => ['scenes', 'session-recordings', 'player', 'sessionRecordingPlayerLogic', key]),
    props({} as SessionRecordingPlayerLogicProps),
    key((props: SessionRecordingPlayerLogicProps) => `${props.playerKey}-${props.sessionRecordingId}`),
    connect(
        ({
            sessionRecordingId,
            sessionRecordingData,
            playerKey,
            recordingStartTime,
        }: SessionRecordingPlayerLogicProps) => ({
            values: [
                sessionRecordingDataLogic({ sessionRecordingId, recordingStartTime, sessionRecordingData }),
                [
                    'sessionRecordingId',
                    'sessionPlayerData',
                    'sessionPlayerSnapshotDataLoading',
                    'sessionPlayerMetaDataLoading',
                    'loadMetaTimeMs',
                    'loadFirstSnapshotTimeMs',
                    'loadAllSnapshotsTimeMs',
                ],
                sharedListLogic({ sessionRecordingId, playerKey }),
                ['tab'],
                playerSettingsLogic,
                ['speed', 'skipInactivitySetting', 'isFullScreen'],
                userLogic,
                ['hasAvailableFeature'],
            ],
            actions: [
                sessionRecordingDataLogic({ sessionRecordingId, recordingStartTime, sessionRecordingData }),
                ['loadRecordingSnapshotsSuccess', 'loadRecordingSnapshotsFailure', 'loadRecordingMetaSuccess'],
                sharedListLogic({ sessionRecordingId, playerKey }),
                ['setTab'],
                playerSettingsLogic,
                ['setSpeed', 'setSkipInactivitySetting', 'setIsFullScreen'],
                eventUsageLogic,
                [
                    'reportNextRecordingTriggered',
                    'reportRecordingPlayerSkipInactivityToggled',
                    'reportRecordingPlayerSpeedChanged',
                    'reportRecordingViewedSummary',
                    'reportRecordingExportedToFile',
                ],
            ],
        })
    ),
    propsChanged(({ actions, props: { matching } }, { matching: oldMatching }) => {
        // Ensures that if filter results change, then matching results in this player logic will also change
        if (!equal(matching, oldMatching)) {
            actions.setMatching(matching)
        }
    }),
    actions({
        tryInitReplayer: () => true,
        setPlayer: (player: Player | null) => ({ player }),
        setPlay: true,
        setPause: true,
        setEndReached: (reached: boolean = true) => ({ reached }),
        startBuffer: true,
        endBuffer: true,
        startScrub: true,
        endScrub: true,
        setErrorPlayerState: (show: boolean) => ({ show }),
        setSkippingInactivity: (isSkippingInactivity: boolean) => ({ isSkippingInactivity }),
        syncPlayerSpeed: true,
        setCurrentPlayerPosition: (playerPosition: PlayerPosition | null) => ({ playerPosition }),
        setScale: (scale: number) => ({ scale }),
        togglePlayPause: true,
        seek: (playerPosition: PlayerPosition | null, forcePlay: boolean = false) => ({ playerPosition, forcePlay }),
        seekForward: (amount?: number) => ({ amount }),
        seekBackward: (amount?: number) => ({ amount }),
        resolvePlayerState: true,
        updateAnimation: true,
        stopAnimation: true,
        setCurrentSegment: (segment: RecordingSegment) => ({ segment }),
        setRootFrame: (frame: HTMLDivElement) => ({ frame }),
        checkBufferingCompleted: true,
        initializePlayerFromStart: true,
        incrementErrorCount: true,
        incrementWarningCount: true,
        setMatching: (matching: SessionRecordingType['matching_events']) => ({ matching }),
        updateFromMetadata: true,
        exportRecordingToFile: true,
    }),
    reducers(({ props }) => ({
        rootFrame: [
            null as HTMLDivElement | null,
            {
                setRootFrame: (_, { frame }) => frame,
            },
        ],
        player: [
            null as Player | null,
            {
                setPlayer: (_, { player }) => player,
            },
        ],
        currentPlayerPosition: [
            null as PlayerPosition | null,
            {
                setCurrentPlayerPosition: (_, { playerPosition }) => playerPosition,
            },
        ],
        currentSegment: [
            null as RecordingSegment | null,
            {
                setCurrentSegment: (_, { segment }) => segment,
            },
        ],
        isSkippingInactivity: [false, { setSkippingInactivity: (_, { isSkippingInactivity }) => isSkippingInactivity }],
        scale: [
            1,
            {
                setScale: (_, { scale }) => scale,
            },
        ],
        playingState: [
            SessionPlayerState.PLAY as SessionPlayerState.PLAY | SessionPlayerState.PAUSE,
            {
                setPlay: () => SessionPlayerState.PLAY,
                setPause: () => SessionPlayerState.PAUSE,
            },
        ],
        isBuffering: [true, { startBuffer: () => true, endBuffer: () => false }],
        isErrored: [false, { setErrorPlayerState: (_, { show }) => show }],
        isScrubbing: [false, { startScrub: () => true, endScrub: () => false }],

        errorCount: [0, { incrementErrorCount: (prevErrorCount, {}) => prevErrorCount + 1 }],
        warningCount: [0, { incrementWarningCount: (prevWarningCount, {}) => prevWarningCount + 1 }],
        matching: [
            props.matching ?? ([] as SessionRecordingType['matching_events']),
            {
                setMatching: (_, { matching }) => matching,
            },
        ],
        endReached: [
            false,
            {
                setEndReached: (_, { reached }) => reached,
                tryInitReplayer: () => false,
                setCurrentPlayerPosition: () => false,
            },
        ],
    })),
    selectors({
        currentPlayerState: [
            (selectors) => [
                selectors.playingState,
                selectors.isBuffering,
                selectors.isErrored,
                selectors.isScrubbing,
                selectors.isSkippingInactivity,
            ],
            (playingState, isBuffering, isErrored, isScrubbing, isSkippingInactivity) => {
                if (isScrubbing) {
                    // If scrubbing, playingState takes precedence
                    return playingState
                }
                if (isErrored) {
                    return SessionPlayerState.ERROR
                }
                if (isBuffering) {
                    return SessionPlayerState.BUFFER
                }
                if (isSkippingInactivity && playingState !== SessionPlayerState.PAUSE) {
                    return SessionPlayerState.SKIP
                }
                return playingState
            },
        ],
        currentPlayerTime: [
            (selectors) => [selectors.currentPlayerPosition, selectors.sessionPlayerData],
            (currentPlayerPosition, sessionPlayerData) => {
                if (sessionPlayerData?.metadata?.segments && currentPlayerPosition) {
                    return getPlayerTimeFromPlayerPosition(currentPlayerPosition, sessionPlayerData?.metadata?.segments)
                }
                return 0
            },
        ],
        jumpTimeMs: [(selectors) => [selectors.speed], (speed) => 10 * 1000 * speed],
        matchingEvents: [
            (s) => [s.matching],
            (matching) => (matching ?? []).map((filterMatches) => filterMatches.events).flat(),
        ],
        recordingStartTime: [
            () => [(_, props) => props.recordingStartTime],
            (recordingStartTime) => recordingStartTime ?? null,
        ],
    }),
    listeners(({ props, values, actions, cache }) => ({
        setRootFrame: () => {
            actions.tryInitReplayer()
        },
        tryInitReplayer: () => {
            // Tries to initialize a new player
            const windowId: string | null = values.currentPlayerPosition?.windowId ?? null
            actions.setPlayer(null)
            if (values.rootFrame) {
                values.rootFrame.innerHTML = '' // Clear the previously drawn frames
            }
            if (
                !values.rootFrame ||
                windowId === null ||
                !values.sessionPlayerData.snapshotsByWindowId[windowId] ||
                values.sessionPlayerData.snapshotsByWindowId[windowId].length < 2
            ) {
                actions.setPlayer(null)
                return
            }
            const replayer = new Replayer(values.sessionPlayerData.snapshotsByWindowId[windowId], {
                root: values.rootFrame,
                triggerFocus: false,
                insertStyleRules: [
                    `.ph-no-capture {   background-image: url("data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMTYiIGhlaWdodD0iMTYiIHZpZXdCb3g9IjAgMCAxNiAxNiIgZmlsbD0ibm9uZSIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj4KPHJlY3Qgd2lkdGg9IjE2IiBoZWlnaHQ9IjE2IiBmaWxsPSJibGFjayIvPgo8cGF0aCBkPSJNOCAwSDE2TDAgMTZWOEw4IDBaIiBmaWxsPSIjMkQyRDJEIi8+CjxwYXRoIGQ9Ik0xNiA4VjE2SDhMMTYgOFoiIGZpbGw9IiMyRDJEMkQiLz4KPC9zdmc+Cg=="); }`,
                ],
            })
            actions.setPlayer({ replayer, windowId })
        },
        setPlayer: ({ player }) => {
            if (player) {
                actions.seek(values.currentPlayerPosition)
                actions.syncPlayerSpeed()
            }
        },
        setCurrentSegment: ({ segment }) => {
            // Check if we should we skip this segment
            if (!segment.isActive && values.skipInactivitySetting) {
                actions.setSkippingInactivity(true)
            } else {
                actions.setSkippingInactivity(false)
            }

            // Check if the new segment is for a different window_id than the last one
            // If so, we need to re-initialize the player
            if (values.player && values.player.windowId !== segment.windowId) {
                values.player?.replayer?.pause()
                actions.tryInitReplayer()
            }
            actions.seek(values.currentPlayerPosition)
        },
        setSkipInactivitySetting: ({ skipInactivitySetting }) => {
            actions.reportRecordingPlayerSkipInactivityToggled(skipInactivitySetting)
            if (!values.currentSegment?.isActive && skipInactivitySetting) {
                actions.setSkippingInactivity(true)
            } else {
                actions.setSkippingInactivity(false)
            }
        },
        setSkippingInactivity: () => {
            actions.syncPlayerSpeed()
        },
        syncPlayerSpeed: () => {
            if (values.isSkippingInactivity) {
                // Sets speed to skip section in max 1 second
                const secondsToSkip =
                    ((values.currentSegment?.endPlayerPosition?.time ?? 0) -
                        (values.currentPlayerPosition?.time ?? 0)) /
                    1000
                const skipSpeed = Math.max(50, secondsToSkip)
                values.player?.replayer?.setConfig({ speed: skipSpeed })
            } else {
                values.player?.replayer?.setConfig({ speed: values.speed })
            }
        },
        checkBufferingCompleted: () => {
            // If buffering has completed, resume last playing state
            if (
                values.currentPlayerPosition &&
                values.sessionPlayerData.bufferedTo &&
                values.currentPlayerState === SessionPlayerState.BUFFER &&
                comparePlayerPositions(
                    values.currentPlayerPosition,
                    values.sessionPlayerData.bufferedTo,
                    values.sessionPlayerData.metadata.segments
                ) < 0
            ) {
                actions.endBuffer()
                actions.seek(values.currentPlayerPosition)
            }
        },
        initializePlayerFromStart: () => {
            const initialSegment = values.sessionPlayerData?.metadata?.segments[0]
            if (initialSegment) {
                actions.setCurrentSegment(initialSegment)
                actions.setCurrentPlayerPosition(initialSegment.startPlayerPosition)

                if (!values.player) {
                    actions.tryInitReplayer()
                }

                // Check for the "t" search param in the url
                if (!cache.initializedFromUrl) {
                    const searchParams = fromParamsGivenUrl(window.location.search)
                    if (searchParams.t) {
                        const newPosition = getPlayerPositionFromPlayerTime(
                            Number(searchParams.t) * 1000,
                            values.sessionPlayerData?.metadata?.segments
                        )
                        actions.seek(newPosition)
                        cache.initializedFromUrl = true
                    }
                }
            }
        },
        updateFromMetadata: async (_, breakpoint) => {
            // On loading more of the recording, trigger some state changes
            const currentEvents = values.player?.replayer?.service.state.context.events ?? []
            const eventsToAdd = []
            if (values.currentSegment?.windowId !== undefined) {
                eventsToAdd.push(
                    ...(values.sessionPlayerData.snapshotsByWindowId[values.currentSegment?.windowId] ?? []).slice(
                        currentEvents.length
                    )
                )
            }

            // If replayer isn't initialized, it will be initialized with the already loaded snapshots
            if (!!values.player?.replayer) {
                for (const event of eventsToAdd) {
                    await values.player?.replayer?.addEvent(event)
                }
            } else {
                actions.initializePlayerFromStart()
            }
            actions.checkBufferingCompleted()
            breakpoint()
        },
        loadRecordingMetaSuccess: async () => {
            // As the connected data logic may be preloaded we call a shared function here and on mount
            actions.updateFromMetadata()
        },

        loadRecordingSnapshotsSuccess: async () => {
            // As the connected data logic may be preloaded we call a shared function here and on mount
            actions.updateFromMetadata()
        },

        loadRecordingSnapshotsFailure: () => {
            if (Object.keys(values.sessionPlayerData.snapshotsByWindowId).length === 0) {
                actions.setErrorPlayerState(true)
            }
        },
        setPlay: () => {
            actions.stopAnimation()
            actions.syncPlayerSpeed() // hotfix: speed changes on player state change

            // Use the start of the current segment if there is no currentPlayerPosition
            // (theoretically, should never happen, but Typescript doesn't know that)

            let nextPlayerPosition = values.currentPlayerPosition || values.currentSegment?.startPlayerPosition

            if (values.endReached) {
                nextPlayerPosition = values.sessionPlayerData.metadata.segments[0].startPlayerPosition
            }

            actions.setEndReached(false)

            if (nextPlayerPosition) {
                actions.seek(nextPlayerPosition, true)
            }
        },
        setPause: () => {
            actions.stopAnimation()
            actions.syncPlayerSpeed() // hotfix: speed changes on player state change
            values.player?.replayer?.pause()
        },
        setEndReached: ({ reached }) => {
            if (reached) {
                actions.setPause()
            }
        },
        startBuffer: () => {
            actions.stopAnimation()
        },
        setErrorPlayerState: ({ show }) => {
            if (show) {
                actions.stopAnimation()
            }
        },
        startScrub: () => {
            actions.stopAnimation()
        },
        setSpeed: ({ speed }) => {
            actions.reportRecordingPlayerSpeedChanged(speed)
            actions.syncPlayerSpeed()
        },
        seek: async ({ playerPosition, forcePlay }, breakpoint) => {
            actions.stopAnimation()
            actions.setCurrentPlayerPosition(playerPosition)

            // Check if we're seeking to a new segment
            let nextSegment = null
            if (playerPosition && values.sessionPlayerData?.metadata) {
                nextSegment = getSegmentFromPlayerPosition(playerPosition, values.sessionPlayerData.metadata.segments)
                if (
                    nextSegment &&
                    (nextSegment.windowId !== values.currentSegment?.windowId ||
                        nextSegment.startTimeEpochMs !== values.currentSegment?.startTimeEpochMs)
                ) {
                    actions.setCurrentSegment(nextSegment)
                }
            }

            // If not currently loading anything and part of the recording hasn't loaded, set error state
            if (
                (!values.sessionPlayerSnapshotDataLoading && !values.sessionPlayerData.bufferedTo) ||
                (!values.sessionPlayerSnapshotDataLoading &&
                    !!values.sessionPlayerData?.bufferedTo &&
                    !!playerPosition &&
                    !!values.currentSegment &&
                    comparePlayerPositions(
                        playerPosition,
                        values.sessionPlayerData.bufferedTo,
                        values.sessionPlayerData.metadata.segments
                    ) > 0)
            ) {
                values.player?.replayer?.pause()
                actions.endBuffer()
                actions.setErrorPlayerState(true)
            }

            // If next time is greater than last buffered time, set to buffering
            else if (
                !values.sessionPlayerData?.bufferedTo ||
                !playerPosition ||
                !values.currentSegment ||
                comparePlayerPositions(
                    playerPosition,
                    values.sessionPlayerData.bufferedTo,
                    values.sessionPlayerData.metadata.segments
                ) > 0
            ) {
                values.player?.replayer?.pause()
                actions.startBuffer()
                actions.setErrorPlayerState(false)
            }

            // If not forced to play and if last playing state was pause, pause
            else if (!forcePlay && values.currentPlayerState === SessionPlayerState.PAUSE) {
                values.player?.replayer?.pause(playerPosition.time)
                actions.endBuffer()
                actions.setErrorPlayerState(false)
            }
            // Otherwise play
            else {
                values.player?.replayer?.play(playerPosition.time)
                actions.updateAnimation()
                actions.endBuffer()
                actions.setErrorPlayerState(false)
            }
            breakpoint()
        },
        seekForward: ({ amount = values.jumpTimeMs }) => {
            if (!values.currentPlayerPosition) {
                return
            }
            const currentPlayerTime = getPlayerTimeFromPlayerPosition(
                values.currentPlayerPosition,
                values.sessionPlayerData.metadata.segments
            )
            if (currentPlayerTime !== null) {
                const nextPlayerTime = currentPlayerTime + amount
                let nextPlayerPosition = getPlayerPositionFromPlayerTime(
                    nextPlayerTime,
                    values.sessionPlayerData.metadata.segments
                )
                if (!nextPlayerPosition) {
                    // At the end of the recording. Pause the player and set to the end of the recording
                    actions.setEndReached()
                    nextPlayerPosition = values.sessionPlayerData.metadata.segments.slice(-1)[0].endPlayerPosition
                }
                actions.seek(nextPlayerPosition)
            }
        },
        seekBackward: ({ amount = values.jumpTimeMs }) => {
            if (!values.currentPlayerPosition) {
                return
            }

            actions.setEndReached(false)

            const currentPlayerTime = getPlayerTimeFromPlayerPosition(
                values.currentPlayerPosition,
                values.sessionPlayerData.metadata.segments
            )
            if (currentPlayerTime !== null) {
                const nextPlayerTime = Math.max(currentPlayerTime - amount, 0)
                const nextPlayerPosition = getPlayerPositionFromPlayerTime(
                    nextPlayerTime,
                    values.sessionPlayerData.metadata.segments
                )

                actions.seek(nextPlayerPosition)
            }
        },

        togglePlayPause: () => {
            // If buffering, toggle is a noop
            if (values.currentPlayerState === SessionPlayerState.BUFFER) {
                return
            }
            // If paused, start playing
            if (values.currentPlayerState === SessionPlayerState.PAUSE) {
                actions.setPlay()
            }
            // If playing, pause
            else {
                actions.setPause()
            }
        },
        updateAnimation: () => {
            // The main loop of the player. Called on each frame
            const playerTime = values.player?.replayer?.getCurrentTime()
            let nextPlayerPosition: PlayerPosition | null = null
            if (playerTime !== undefined && values.currentSegment) {
                nextPlayerPosition = {
                    windowId: values.currentSegment.windowId,
                    // Cap the player position to the end of the segment. Below, we'll check if
                    // the player is at the end of the segment and if so, we'll go to the next one
                    time: Math.min(playerTime, values.currentSegment.endPlayerPosition.time),
                }
            }

            // If we're beyond the current segments, move to next segments if there is one
            if (
                nextPlayerPosition &&
                values.currentSegment?.endPlayerPosition &&
                comparePlayerPositions(
                    nextPlayerPosition,
                    values.currentSegment?.endPlayerPosition,
                    values.sessionPlayerData.metadata.segments
                ) >= 0
            ) {
                const nextSegmentIndex = values.sessionPlayerData.metadata.segments.indexOf(values.currentSegment) + 1
                if (nextSegmentIndex < values.sessionPlayerData.metadata.segments.length) {
                    const nextSegment = values.sessionPlayerData.metadata.segments[nextSegmentIndex]
                    actions.setCurrentPlayerPosition(nextSegment.startPlayerPosition)
                    actions.setCurrentSegment(nextSegment)
                } else {
                    // At the end of the recording. Pause the player and set fully to the end
                    actions.setEndReached()
                }
            }
            // If next position tries to access snapshot that is not loaded, show error state
            else if (
                !!values.sessionPlayerData?.bufferedTo &&
                !!nextPlayerPosition &&
                !!values.currentSegment &&
                comparePlayerPositions(
                    nextPlayerPosition,
                    values.sessionPlayerData.bufferedTo,
                    values.sessionPlayerData.metadata.segments
                ) > 0 &&
                !values.sessionPlayerSnapshotDataLoading
            ) {
                values.player?.replayer?.pause()
                actions.endBuffer()
                actions.setErrorPlayerState(true)
            }

            // If we're beyond buffered position, set to buffering
            else if (
                !values.sessionPlayerData.bufferedTo ||
                !nextPlayerPosition ||
                !values.currentSegment ||
                comparePlayerPositions(
                    nextPlayerPosition,
                    values.sessionPlayerData.bufferedTo,
                    values.sessionPlayerData.metadata.segments
                ) > 0
            ) {
                // Pause only the animation, not our player, so it will restart
                // when the buffering progresses
                values.player?.replayer?.pause()
                actions.startBuffer()
                actions.setErrorPlayerState(false)
            } else {
                // The normal loop. Progress the player position and continue the loop
                actions.setCurrentPlayerPosition(nextPlayerPosition)
                cache.timer = requestAnimationFrame(actions.updateAnimation)
            }
        },
        stopAnimation: () => {
            if (cache.timer) {
                cancelAnimationFrame(cache.timer)
            }
        },

        exportRecordingToFile: async () => {
            if (!values.sessionPlayerData) {
                return
            }

            if (!values.hasAvailableFeature(AvailableFeature.RECORDINGS_FILE_EXPORT)) {
                openBillingPopupModal({
                    title: 'Unlock recording exports',
                    description:
                        'Export recordings to a file that can be stored wherever you like and loaded back into PostHog for playback at any time.',
                })
                return
            }

            const doExport = async (): Promise<void> => {
                while (values.sessionPlayerData.next) {
                    await delay(1000)
                }

                const payload: ExportedSessionRecordingFile = {
                    version: '2022-12-02',
                    data: values.sessionPlayerData,
                }
                const recordingFile = new File(
                    [JSON.stringify(payload)],
                    `export-${props.sessionRecordingId}.ph-recording.json`,
                    { type: 'application/json' }
                )

                downloadFile(recordingFile)
                actions.reportRecordingExportedToFile()
            }

            await lemonToast.promise(doExport(), {
                success: 'Export complete!',
                error: 'Export failed!',
                pending: 'Exporting recording...',
            })
        },
    })),
    windowValues({
        isSmallScreen: (window: any) => window.innerWidth < getBreakpoint('md'),
    }),
    events(({ values, actions, cache }) => ({
        beforeUnmount: () => {
            values.player?.replayer?.pause()
            actions.setPlayer(null)
            if (cache.originalWarning) {
                console.warn = cache.originalWarning
            }
            if (cache.errorHandler) {
                window.removeEventListener('error', cache.errorHandler)
            }
            actions.reportRecordingViewedSummary({
                viewed_time_ms: cache.openTime !== undefined ? performance.now() - cache.openTime : undefined,
                recording_duration_ms: values.sessionPlayerData?.metadata
                    ? values.sessionPlayerData.metadata.recordingDurationMs
                    : undefined,
                recording_age_days:
                    values.sessionPlayerData?.metadata && values.sessionPlayerData?.metadata.segments.length > 0
                        ? Math.floor(
                              (Date.now() - values.sessionPlayerData.metadata.segments[0].startTimeEpochMs) /
                                  (1000 * 60 * 60 * 24)
                          )
                        : undefined,
                meta_data_load_time_ms: values.loadMetaTimeMs ?? undefined,
                first_snapshot_load_time_ms: values.loadFirstSnapshotTimeMs ?? undefined,
                first_snapshot_and_meta_load_time_ms:
                    values.loadFirstSnapshotTimeMs !== null && values.loadMetaTimeMs !== null
                        ? Math.max(values.loadFirstSnapshotTimeMs, values.loadMetaTimeMs)
                        : undefined,
                all_snapshots_load_time_ms: values.loadAllSnapshotsTimeMs ?? undefined,
                rrweb_warning_count: values.warningCount,
                error_count_during_recording_playback: values.errorCount,
            })
        },
        afterMount: () => {
            if (!values.sessionPlayerSnapshotDataLoading || !values.sessionPlayerMetaDataLoading) {
                // If either value is not loading that indicates we have already loaded and should trigger it
                actions.updateFromMetadata()
            }

            cache.openTime = performance.now()

            cache.errorHandler = () => {
                actions.incrementErrorCount()
            }
            window.addEventListener('error', cache.errorHandler)
            cache.originalWarning = console.warn
            console.warn = function (...args: Array<unknown>) {
                if (typeof args[0] === 'string' && args[0].includes('[replayer]')) {
                    actions.incrementWarningCount()
                }
                cache.originalWarning(...args)
            }
        },
    })),
])

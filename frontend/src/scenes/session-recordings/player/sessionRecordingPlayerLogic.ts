import {
    actions,
    afterMount,
    beforeUnmount,
    connect,
    kea,
    key,
    listeners,
    path,
    props,
    propsChanged,
    reducers,
    selectors,
} from 'kea'
import { windowValues } from 'kea-window-values'
import type { sessionRecordingPlayerLogicType } from './sessionRecordingPlayerLogicType'
import { Replayer } from 'rrweb'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import {
    AvailableFeature,
    MatchedRecording,
    RecordingSegment,
    SessionPlayerData,
    SessionPlayerState,
    SessionRecordingId,
    SessionRecordingType,
} from '~/types'
import { getBreakpoint } from 'lib/utils/responsiveUtils'
import { sessionRecordingDataLogic } from 'scenes/session-recordings/player/sessionRecordingDataLogic'
import { deleteRecording } from './utils/playerUtils'
import { playerSettingsLogic } from './playerSettingsLogic'
import equal from 'fast-deep-equal'
import { clamp, downloadFile, fromParamsGivenUrl } from 'lib/utils'
import { lemonToast } from '@posthog/lemon-ui'
import { delay } from 'kea-test-utils'
import { userLogic } from 'scenes/userLogic'
import { openBillingPopupModal } from 'scenes/billing/BillingPopup'
import { sessionRecordingsListLogic } from 'scenes/session-recordings/playlist/sessionRecordingsListLogic'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import { wrapConsole } from 'lib/utils/wrapConsole'
import { SessionRecordingPlayerExplorerProps } from './view-explorer/SessionRecordingPlayerExplorer'
import { createExportedSessionRecording } from '../file-playback/sessionRecordingFilePlaybackLogic'
import { RefObject } from 'react'

export const PLAYBACK_SPEEDS = [0.5, 1, 2, 3, 4, 8, 16]
export const ONE_FRAME_MS = 100 // We don't really have frames but this feels granular enough

export interface Player {
    replayer: Replayer
    windowId: string
}

export enum SessionRecordingPlayerMode {
    Standard = 'standard',
    Sharing = 'sharing',
    Notebook = 'notebook',
}

// This is the basic props used by most sub-logics
export interface SessionRecordingLogicProps {
    sessionRecordingId: SessionRecordingId
    playerKey: string
}

export interface SessionRecordingPlayerLogicProps extends SessionRecordingLogicProps {
    sessionRecordingData?: SessionPlayerData
    playlistShortId?: string
    matching?: MatchedRecording[]
    recordingStartTime?: string
    nextSessionRecording?: Partial<SessionRecordingType>
    autoPlay?: boolean
    mode?: SessionRecordingPlayerMode
    playerRef?: RefObject<HTMLDivElement>
}

export const sessionRecordingPlayerLogic = kea<sessionRecordingPlayerLogicType>([
    path((key) => ['scenes', 'session-recordings', 'player', 'sessionRecordingPlayerLogic', key]),
    props({} as SessionRecordingPlayerLogicProps),
    key((props: SessionRecordingPlayerLogicProps) => `${props.playerKey}-${props.sessionRecordingId}`),
    connect((props: SessionRecordingPlayerLogicProps) => ({
        values: [
            sessionRecordingDataLogic(props),
            ['fullLoad', 'sessionPlayerData', 'sessionPlayerSnapshotDataLoading', 'sessionPlayerMetaDataLoading'],
            playerSettingsLogic,
            ['speed', 'skipInactivitySetting'],
            userLogic,
            ['hasAvailableFeature'],
        ],
        actions: [
            sessionRecordingDataLogic(props),
            [
                'loadRecording',
                'loadRecordingSnapshotsSuccess',
                'loadRecordingSnapshotsV2Success',
                'loadRecordingSnapshotsFailure',
                'loadRecordingSnapshotsV2Failure',
                'loadRecordingMetaSuccess',
            ],
            playerSettingsLogic,
            ['setSpeed', 'setSkipInactivitySetting'],
            eventUsageLogic,
            [
                'reportNextRecordingTriggered',
                'reportRecordingPlayerSkipInactivityToggled',
                'reportRecordingPlayerSpeedChanged',
                'reportRecordingViewedSummary',
                'reportRecordingExportedToFile',
            ],
        ],
    })),
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
        setCurrentTimestamp: (timestamp: number) => ({ timestamp }),
        setScale: (scale: number) => ({ scale }),
        togglePlayPause: true,
        seekToTimestamp: (timestamp: number, forcePlay: boolean = false) => ({ timestamp, forcePlay }),
        seekToTime: (timeInMilliseconds: number) => ({ timeInMilliseconds }),
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
        incrementWarningCount: (count: number = 1) => ({ count }),
        setMatching: (matching: SessionRecordingType['matching_events']) => ({ matching }),
        updateFromMetadata: true,
        exportRecordingToFile: true,
        deleteRecording: true,
        openExplorer: true,
        closeExplorer: true,
        setExplorerProps: (props: SessionRecordingPlayerExplorerProps | null) => ({ props }),
        setIsFullScreen: (isFullScreen: boolean) => ({ isFullScreen }),
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
        currentTimestamp: [
            undefined as number | undefined,
            {
                setCurrentTimestamp: (_, { timestamp }) => timestamp,
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
        warningCount: [0, { incrementWarningCount: (prevWarningCount, { count }) => prevWarningCount + count }],
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
                setCurrentTimestamp: () => false,
            },
        ],
        explorerMode: [
            null as SessionRecordingPlayerExplorerProps | null,
            {
                setExplorerProps: (_, { props }) => props,
                closeExplorer: () => null,
            },
        ],
        isFullScreen: [
            false,
            {
                setIsFullScreen: (_, { isFullScreen }) => isFullScreen,
            },
        ],
    })),
    selectors({
        // Prop references for use by other logics
        sessionRecordingId: [() => [(_, props) => props], (props): string => props.sessionRecordingId],
        logicProps: [() => [(_, props) => props], (props): SessionRecordingPlayerLogicProps => props],

        currentPlayerState: [
            (s) => [s.playingState, s.fullLoad, s.isBuffering, s.isErrored, s.isScrubbing, s.isSkippingInactivity],
            (playingState, fullLoad, isBuffering, isErrored, isScrubbing, isSkippingInactivity) => {
                if (isScrubbing) {
                    // If scrubbing, playingState takes precedence
                    return playingState
                }
                if (!fullLoad) {
                    return SessionPlayerState.READY
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
        // Useful for the relative time in the context of the whole recording
        currentPlayerTime: [
            (s) => [s.currentTimestamp, s.sessionPlayerData],
            (currentTimestamp, sessionPlayerData) => {
                return Math.max(0, (currentTimestamp ?? 0) - (sessionPlayerData?.start?.valueOf() ?? 0))
            },
        ],
        // The relative time for the player, i.e. the offset between the current timestamp, and the window start for the current segment
        toRRwebPlayerTime: [
            (s) => [s.sessionPlayerData, s.currentSegment],
            (sessionPlayerData, currentSegment) => {
                return (timestamp: number): number | undefined => {
                    if (!currentSegment || !currentSegment.windowId) {
                        return
                    }

                    const snaphots = sessionPlayerData.snapshotsByWindowId[currentSegment.windowId]

                    return Math.max(0, timestamp - snaphots[0].timestamp)
                }
            },
        ],

        // The relative time for the player, i.e. the offset between the current timestamp, and the window start for the current segment
        fromRRwebPlayerTime: [
            (s) => [s.sessionPlayerData, s.currentSegment],
            (sessionPlayerData, currentSegment) => {
                return (time?: number): number | undefined => {
                    if (time === undefined || !currentSegment?.windowId) {
                        return
                    }
                    const snaphots = sessionPlayerData.snapshotsByWindowId[currentSegment.windowId]
                    return snaphots[0].timestamp + time
                }
            },
        ],

        jumpTimeMs: [(selectors) => [selectors.speed], (speed) => 10 * 1000 * speed],
        matchingEvents: [
            (s) => [s.matching],
            (matching) => (matching ?? []).map((filterMatches) => filterMatches.events).flat(),
        ],

        playerSpeed: [
            (s) => [s.speed, s.isSkippingInactivity, s.currentSegment, s.currentTimestamp],
            (speed, isSkippingInactivity, currentSegment, currentTimestamp) => {
                if (isSkippingInactivity) {
                    const secondsToSkip = ((currentSegment?.endTimestamp ?? 0) - (currentTimestamp ?? 0)) / 1000
                    const skipSpeed = Math.max(50, secondsToSkip)

                    return skipSpeed
                } else {
                    return speed
                }
            },
        ],
        segmentForTimestamp: [
            (s) => [s.sessionPlayerData],
            (sessionPlayerData) => {
                return (timestamp?: number): RecordingSegment | null => {
                    if (timestamp === undefined) {
                        return null
                    }
                    for (const segment of sessionPlayerData.segments) {
                        if (segment.startTimestamp <= timestamp && segment.endTimestamp >= timestamp) {
                            return segment
                        }
                    }
                    return null
                }
            },
        ],
    }),
    listeners(({ props, values, actions, cache }) => ({
        setRootFrame: () => {
            actions.tryInitReplayer()
        },
        tryInitReplayer: () => {
            // Tries to initialize a new player
            const windowId = values.segmentForTimestamp(values.currentTimestamp)?.windowId

            actions.setPlayer(null)

            if (values.rootFrame) {
                values.rootFrame.innerHTML = '' // Clear the previously drawn frames
            }

            if (
                !values.rootFrame ||
                windowId === undefined ||
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
                if (values.currentTimestamp !== undefined) {
                    actions.seekToTimestamp(values.currentTimestamp)
                }
                actions.syncPlayerSpeed()
            }
        },
        setCurrentSegment: ({ segment }) => {
            // Check if we should we skip this segment
            if (!segment.isActive && values.skipInactivitySetting && segment.kind !== 'buffer') {
                actions.setSkippingInactivity(true)
            } else {
                actions.setSkippingInactivity(false)
            }

            // Check if the new segment is for a different window_id than the last one
            // If so, we need to re-initialize the player
            if (!values.player || values.player.windowId !== segment.windowId) {
                values.player?.replayer?.pause()
                actions.tryInitReplayer()
            }
            if (values.currentTimestamp !== undefined) {
                actions.seekToTimestamp(values.currentTimestamp)
            }
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
            values.player?.replayer?.setConfig({ speed: values.playerSpeed })
        },
        checkBufferingCompleted: () => {
            // If buffering has completed, resume last playing state
            if (values.currentTimestamp === undefined) {
                return
            }
            const isBuffering = values.segmentForTimestamp(values.currentTimestamp)?.kind === 'buffer'

            if (values.currentPlayerState === SessionPlayerState.BUFFER && !isBuffering) {
                actions.endBuffer()
                actions.seekToTimestamp(values.currentTimestamp)
            }
        },
        initializePlayerFromStart: () => {
            const initialSegment = values.sessionPlayerData?.segments[0]
            if (initialSegment) {
                // Check for the "t" search param in the url on first load
                if (!cache.hasInitialized) {
                    cache.hasInitialized = true
                    const searchParams = fromParamsGivenUrl(window.location.search)
                    if (searchParams.timestamp) {
                        const desiredStartTime = Number(searchParams.timestamp)
                        actions.seekToTimestamp(desiredStartTime, true)
                    } else if (searchParams.t) {
                        const desiredStartTime = Number(searchParams.t) * 1000
                        actions.seekToTime(desiredStartTime)
                    }
                }

                if (!values.currentTimestamp) {
                    actions.setCurrentTimestamp(initialSegment.startTimestamp)
                }

                actions.setCurrentSegment(initialSegment)
            }
        },
        updateFromMetadata: async (_, breakpoint) => {
            // On loading more of the recording, trigger some state changes
            const currentEvents = values.player?.replayer?.service.state.context.events ?? []
            const eventsToAdd = []

            if (values.currentSegment?.windowId !== undefined) {
                // TODO: Probbaly need to check for dedupes here....
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
            }

            if (!values.currentTimestamp) {
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
        loadRecordingSnapshotsV2Success: async () => {
            // As the connected data logic may be preloaded we call a shared function here and on mount
            actions.updateFromMetadata()
        },

        loadRecordingSnapshotsFailure: () => {
            if (Object.keys(values.sessionPlayerData.snapshotsByWindowId).length === 0) {
                console.error('PostHog Recording Playback Error: No snapshots loaded')
                actions.setErrorPlayerState(true)
            }
        },
        loadRecordingSnapshotsV2Failure: () => {
            if (Object.keys(values.sessionPlayerData.snapshotsByWindowId).length === 0) {
                console.error('PostHog Recording Playback Error: No snapshots loaded')
                actions.setErrorPlayerState(true)
            }
        },
        setPlay: () => {
            actions.stopAnimation()
            actions.syncPlayerSpeed() // hotfix: speed changes on player state change

            // Use the start of the current segment if there is no currentTimestamp
            // (theoretically, should never happen, but Typescript doesn't know that)

            let nextTimestamp = values.currentTimestamp || values.currentSegment?.startTimestamp

            if (values.endReached) {
                nextTimestamp = values.sessionPlayerData.segments[0].startTimestamp
            }

            actions.setEndReached(false)

            if (nextTimestamp !== undefined) {
                actions.seekToTimestamp(nextTimestamp, true)
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
                actions.incrementErrorCount()
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
        seekToTimestamp: async ({ timestamp, forcePlay }, breakpoint) => {
            actions.stopAnimation()
            actions.setCurrentTimestamp(timestamp)

            // Check if we're seeking to a new segment
            const segment = values.segmentForTimestamp(timestamp)

            if (segment && segment !== values.currentSegment) {
                actions.setCurrentSegment(segment)
            }

            if (values.currentPlayerState === SessionPlayerState.READY) {
                // We haven't started properly loading yet so nothing to do
            } else if (!values.sessionPlayerSnapshotDataLoading && segment?.kind === 'buffer') {
                // If not currently loading anything and part of the recording hasn't loaded, set error state
                values.player?.replayer?.pause()
                actions.endBuffer()
                console.error("Error: Player tried to seek to a position that hasn't loaded yet")
                actions.setErrorPlayerState(true)
            }

            // If next time is greater than last buffered time, set to buffering
            else if (segment?.kind === 'buffer') {
                values.player?.replayer?.pause()
                actions.startBuffer()
                actions.setErrorPlayerState(false)
            }

            // If not forced to play and if last playing state was pause, pause
            else if (!forcePlay && values.currentPlayerState === SessionPlayerState.PAUSE) {
                values.player?.replayer?.pause(values.toRRwebPlayerTime(timestamp))
                actions.endBuffer()
                actions.setErrorPlayerState(false)
            }
            // Otherwise play
            else {
                values.player?.replayer?.play(values.toRRwebPlayerTime(timestamp))
                actions.updateAnimation()
                actions.endBuffer()
                actions.setErrorPlayerState(false)
            }

            breakpoint()
        },
        seekForward: ({ amount = values.jumpTimeMs }) => {
            actions.seekToTime((values.currentPlayerTime || 0) + amount)
        },
        seekBackward: ({ amount = values.jumpTimeMs }) => {
            actions.seekToTime((values.currentPlayerTime || 0) - amount)
        },

        seekToTime: ({ timeInMilliseconds }) => {
            if (values.currentTimestamp === undefined) {
                return
            }

            if (!values.sessionPlayerData.start || !values.sessionPlayerData.end) {
                return
            }

            const newTimestamp = clamp(
                values.sessionPlayerData.start.valueOf() + timeInMilliseconds,
                values.sessionPlayerData.start.valueOf(),
                values.sessionPlayerData.end.valueOf()
            )

            actions.seekToTimestamp(newTimestamp)
        },

        togglePlayPause: () => {
            if (values.currentPlayerState === SessionPlayerState.READY) {
                actions.loadRecording(true)
                return
            }
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
            const rrwebPlayerTime = values.player?.replayer?.getCurrentTime()
            let newTimestamp = values.fromRRwebPlayerTime(rrwebPlayerTime)

            if (newTimestamp == undefined && values.currentTimestamp) {
                // This can happen if the player is not loaded due to us being in a "gap" segment
                // In this case, we should progress time forward manually
                if (values.currentSegment?.kind === 'gap') {
                    newTimestamp = values.currentTimestamp + values.playerSpeed * (1000 / 60) // rough animation fps
                }
            }

            // If we are beyond the current segment then move to the next one
            if (newTimestamp && values.currentSegment && newTimestamp > values.currentSegment.endTimestamp) {
                const nextSegment = values.segmentForTimestamp(newTimestamp)

                if (nextSegment) {
                    actions.setCurrentTimestamp(Math.max(newTimestamp, nextSegment.startTimestamp))
                    actions.setCurrentSegment(nextSegment)
                } else {
                    // At the end of the recording. Pause the player and set fully to the end
                    actions.setEndReached()
                }
                return
            }

            // If we're beyond buffered position, set to buffering
            if (values.currentSegment?.kind === 'buffer') {
                // Pause only the animation, not our player, so it will restart
                // when the buffering progresses
                values.player?.replayer?.pause()
                actions.startBuffer()
                actions.setErrorPlayerState(false)
                return
            }

            if (newTimestamp !== undefined) {
                // The normal loop. Progress the player position and continue the loop
                actions.setCurrentTimestamp(newTimestamp)
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
                const delaytime = 1000
                let maxWaitTime = 30000
                while (!values.sessionPlayerData.fullyLoaded) {
                    if (maxWaitTime <= 0) {
                        throw new Error('Timeout waiting for recording to load')
                    }
                    maxWaitTime -= delaytime
                    await delay(delaytime)
                }

                const payload = createExportedSessionRecording(sessionRecordingDataLogic(props))

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
        deleteRecording: async () => {
            await deleteRecording(props.sessionRecordingId)

            // Handles locally updating recordings sidebar so that we don't have to call expensive load recordings every time.
            const listLogic =
                !!props.playlistShortId &&
                sessionRecordingsListLogic.isMounted({ playlistShortId: props.playlistShortId })
                    ? // On playlist page
                      sessionRecordingsListLogic({ playlistShortId: props.playlistShortId })
                    : // In any other context with a list of recordings (recent recordings)
                      sessionRecordingsListLogic.findMounted({ updateSearchParams: true })

            if (listLogic) {
                listLogic.actions.loadAllRecordings()
                // Reset selected recording to first one in the list
                listLogic.actions.setSelectedRecordingId(null)
            } else if (router.values.location.pathname.includes('/replay')) {
                // On a page that displays a single recording `replay/:id` that doesn't contain a list
                router.actions.push(urls.replay())
            } else {
                // No-op a modal session recording. Delete icon is hidden in modal contexts since modals should be read only views.
            }
        },
        openExplorer: () => {
            actions.setPause()
            const iframe = values.rootFrame?.querySelector('iframe')
            const iframeHtml = iframe?.contentWindow?.document?.documentElement?.innerHTML
            if (!iframeHtml) {
                return
            }

            actions.setExplorerProps({
                html: iframeHtml,
                width: parseFloat(iframe.width),
                height: parseFloat(iframe.height),
            })
        },

        setIsFullScreen: async ({ isFullScreen }) => {
            if (isFullScreen) {
                try {
                    await props.playerRef?.current?.requestFullscreen()
                } catch (e) {
                    console.warn('Failed to enable native full-screen mode:', e)
                }
            } else if (document.fullscreenElement === props.playerRef?.current) {
                document.exitFullscreen()
            }
        },
    })),
    windowValues({
        isSmallScreen: (window: any) => window.innerWidth < getBreakpoint('md'),
    }),

    beforeUnmount(({ values, actions, cache }) => {
        cache.resetConsoleWarn?.()
        cache.hasInitialized = false
        clearTimeout(cache.consoleWarnDebounceTimer)
        document.removeEventListener('fullscreenchange', cache.fullScreenListener)
        values.player?.replayer?.pause()
        actions.setPlayer(null)
        actions.reportRecordingViewedSummary({
            viewed_time_ms: cache.openTime !== undefined ? performance.now() - cache.openTime : undefined,
            recording_duration_ms: values.sessionPlayerData ? values.sessionPlayerData.durationMs : undefined,
            // TODO: Validate this is correct
            recording_age_days:
                values.sessionPlayerData && values.sessionPlayerData.segments.length > 0
                    ? Math.floor(values.sessionPlayerData.start?.diff(new Date(), 'days') ?? 0)
                    : undefined,
            rrweb_warning_count: values.warningCount,
            error_count_during_recording_playback: values.errorCount,
        })
    }),

    afterMount(({ props, actions, cache }) => {
        cache.fullScreenListener = () => {
            actions.setIsFullScreen(document.fullscreenElement !== null)
        }

        document.addEventListener('fullscreenchange', cache.fullScreenListener)

        if (props.sessionRecordingId) {
            actions.loadRecording(props.autoPlay)
        }

        cache.openTime = performance.now()

        // NOTE: RRweb can log _alot_ of warnings so we debounce the count otherwise we just end up making the performance worse
        let warningCount = 0
        cache.consoleWarnDebounceTimer = null

        const debouncedCounter = (): void => {
            warningCount += 1

            if (!cache.consoleWarnDebounceTimer) {
                cache.consoleWarnDebounceTimer = setTimeout(() => {
                    cache.consoleWarnDebounceTimer = null
                    actions.incrementWarningCount(warningCount)
                    warningCount = 0
                }, 1000)
            }
        }

        cache.resetConsoleWarn = wrapConsole('warn', (args) => {
            if (typeof args[0] === 'string' && args[0].includes('[replayer]')) {
                debouncedCounter()
            }

            return true
        })
    }),
])

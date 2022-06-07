import { MutableRefObject } from 'react'
import { kea } from 'kea'
import type { seekbarLogicType } from './seekbarLogicType'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { sessionRecordingLogic } from 'scenes/session-recordings/sessionRecordingLogic'
import { clamp } from 'lib/utils'
import { PlayerPosition } from '~/types'

import {
    convertPlayerPositionToX,
    convertXToPlayerPosition,
    getPlayerTimeFromPlayerPosition,
    getXPos,
    InteractEvent,
    ReactInteractEvent,
    THUMB_OFFSET,
    THUMB_SIZE,
} from './playerUtils'
export const seekbarLogic = kea<seekbarLogicType>({
    path: ['scenes', 'session-recordings', 'player', 'seekbarLogic'],
    connect: {
        values: [
            sessionRecordingPlayerLogic,
            ['sessionPlayerData', 'currentPlayerPosition'],
            sessionRecordingLogic,
            ['eventsToShow'],
        ],
        actions: [sessionRecordingPlayerLogic, ['seek', 'startScrub', 'endScrub', 'setCurrentPlayerPosition']],
    },
    actions: {
        setThumbLeftPos: (thumbLeftPos: number, shouldSeek: boolean) => ({ thumbLeftPos, shouldSeek }),
        setCursorDiff: (cursorDiff: number) => ({ cursorDiff }),
        handleSeek: (newX: number, shouldSeek: boolean = true) => ({ newX, shouldSeek }),
        handleMove: (event: InteractEvent) => ({ event }),
        handleUp: (event: InteractEvent) => ({ event }),
        handleDown: (event: ReactInteractEvent) => ({ event }),
        handleClick: (event: ReactInteractEvent) => ({ event }),
        handleTickClick: (playerPosition: PlayerPosition) => ({ playerPosition }),
        setSlider: (ref: MutableRefObject<HTMLDivElement | null>) => ({ ref }),
        setThumb: (ref: MutableRefObject<HTMLDivElement | null>) => ({ ref }),
        debouncedSetTime: (time: number) => ({ time }),
        endSeeking: true,
    },
    reducers: {
        thumbLeftPos: [
            -THUMB_OFFSET,
            {
                setThumbLeftPos: (_, { thumbLeftPos }) => thumbLeftPos,
            },
        ],
        cursorDiff: [
            0,
            {
                setCursorDiff: (_, { cursorDiff }) => cursorDiff,
            },
        ],
        slider: [
            null as HTMLDivElement | null,
            {
                setSlider: (_, { ref }) => ref.current,
            },
        ],
        thumb: [
            null as HTMLDivElement | null,
            {
                setThumb: (_, { ref }) => ref.current,
            },
        ],
        isSeeking: [
            false,
            {
                handleSeek: () => true,
                endSeeking: () => false,
            },
        ],
        isScrubbing: [
            false,
            {
                startScrub: () => true,
                endScrub: () => false,
            },
        ],
    },
    selectors: {
        bufferPercent: [
            (selectors) => [selectors.sessionPlayerData],
            (sessionPlayerData) => {
                if (
                    sessionPlayerData?.bufferedTo &&
                    sessionPlayerData?.metadata?.segments &&
                    sessionPlayerData?.metadata?.recordingDurationMs
                ) {
                    const bufferedToPlayerTime =
                        getPlayerTimeFromPlayerPosition(
                            sessionPlayerData.bufferedTo,
                            sessionPlayerData.metadata.segments
                        ) ?? 0
                    return (100 * bufferedToPlayerTime) / sessionPlayerData.metadata.recordingDurationMs
                }
                return 0
            },
        ],
        scrubbingTime: [
            (selectors) => [selectors.thumbLeftPos, selectors.slider, selectors.sessionPlayerData],
            (thumbLeftPos, slider, sessionPlayerData) => {
                if (thumbLeftPos && slider && sessionPlayerData?.metadata?.recordingDurationMs) {
                    return (
                        ((thumbLeftPos + THUMB_OFFSET) / slider.offsetWidth) *
                        sessionPlayerData.metadata.recordingDurationMs
                    )
                }
                return 0
            },
        ],
    },
    listeners: ({ values, actions }) => ({
        setCurrentPlayerPosition: async () => {
            if (!values.slider) {
                return
            }
            // Don't update thumb position if seekbar logic is already seeking and setting the thumb position.
            // Except in one case when the updated thumb position is at the start. This happens when the user
            // scrubs to the end of the recording while playing, and then the player loop restarts the recording.
            if (
                !values.isSeeking ||
                values.currentPlayerPosition === values.sessionPlayerData?.metadata?.segments[0]?.startPlayerPosition
            ) {
                const xValue = values.currentPlayerPosition
                    ? convertPlayerPositionToX(
                          values.currentPlayerPosition,
                          values.slider.offsetWidth,
                          values.sessionPlayerData.metadata.segments,
                          values.sessionPlayerData.metadata.recordingDurationMs
                      )
                    : 0

                actions.setThumbLeftPos(xValue - THUMB_OFFSET, false)
            }
        },

        setThumbLeftPos: ({ thumbLeftPos, shouldSeek }) => {
            if (!values.slider) {
                return
            }
            if (shouldSeek && values.sessionPlayerData?.metadata) {
                const playerPosition = convertXToPlayerPosition(
                    thumbLeftPos + THUMB_OFFSET,
                    values.slider.offsetWidth,
                    values.sessionPlayerData.metadata.segments,
                    values.sessionPlayerData.metadata.recordingDurationMs
                )
                actions.seek(playerPosition)
            }
        },
        handleSeek: async ({ newX, shouldSeek }) => {
            const end = values.slider?.offsetWidth ?? 0
            await actions.setThumbLeftPos(clamp(newX, 0, end) - THUMB_OFFSET, shouldSeek)
            actions.endSeeking()
        },
        handleMove: async ({ event }) => {
            if (!values.slider) {
                return
            }
            actions.startScrub()
            const newX = getXPos(event) - values.cursorDiff - values.slider.getBoundingClientRect().left
            actions.handleSeek(newX, false)
        },
        handleUp: ({ event }) => {
            if (!values.slider) {
                return
            }
            const newX = getXPos(event) - values.cursorDiff - values.slider.getBoundingClientRect().left
            actions.handleSeek(newX)
            actions.endScrub()

            document.removeEventListener('touchmove', actions.handleMove)
            document.removeEventListener('touchend', actions.handleUp)
            document.removeEventListener('mousemove', actions.handleMove)
            document.removeEventListener('mouseup', actions.handleUp)
        },
        handleDown: ({ event }) => {
            if (!values.thumb) {
                return
            }

            actions.startScrub()
            const xPos = getXPos(event)
            let diffFromThumb = xPos - values.thumb.getBoundingClientRect().left - THUMB_OFFSET
            // If click is too far from thumb, move thumb to click position
            if (Math.abs(diffFromThumb) > THUMB_SIZE) {
                diffFromThumb = 0
            }
            actions.setCursorDiff(diffFromThumb)

            document.addEventListener('touchmove', actions.handleMove)
            document.addEventListener('touchend', actions.handleUp)
            document.addEventListener('mousemove', actions.handleMove)
            document.addEventListener('mouseup', actions.handleUp)
        },
        handleTickClick: ({ playerPosition }) => {
            if (!values.isSeeking && values.slider) {
                actions.handleSeek(
                    convertPlayerPositionToX(
                        playerPosition,
                        values.slider.offsetWidth,
                        values.sessionPlayerData.metadata.segments,
                        values.sessionPlayerData.metadata.recordingDurationMs
                    )
                )
            }
        },
    }),
    events: ({ actions, values, cache }) => ({
        afterMount: () => {
            cache.setCurrentPlayerPosition = () => {
                actions.setCurrentPlayerPosition(values.currentPlayerPosition)
            }
            window.addEventListener('resize', cache.setCurrentPlayerPosition)
        },
        beforeUnmount: () => {
            window.removeEventListener('resize', cache.setCurrentPlayerPosition)
        },
    }),
})

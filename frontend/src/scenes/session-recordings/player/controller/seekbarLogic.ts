import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { MutableRefObject } from 'react'

import { clamp } from 'lib/utils'
import {
    SessionRecordingPlayerLogicProps,
    sessionRecordingPlayerLogic,
} from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { InteractEvent, ReactInteractEvent, THUMB_OFFSET, THUMB_SIZE, getXPos } from '../utils/playerUtils'
import type { seekbarLogicType } from './seekbarLogicType'

export const seekbarLogic = kea<seekbarLogicType>([
    path((key) => ['scenes', 'session-recordings', 'player', 'seekbarLogic', key]),
    props({} as SessionRecordingPlayerLogicProps),
    key((props: SessionRecordingPlayerLogicProps) => `${props.playerKey}-${props.sessionRecordingId}`),
    connect((props: SessionRecordingPlayerLogicProps) => ({
        values: [sessionRecordingPlayerLogic(props), ['sessionPlayerData', 'currentPlayerTime']],
        actions: [sessionRecordingPlayerLogic(props), ['seekToTime', 'startScrub', 'endScrub', 'setCurrentTimestamp']],
    })),
    actions({
        setThumbLeftPos: (thumbLeftPos: number, shouldSeek: boolean) => ({ thumbLeftPos, shouldSeek }),
        setCursorDiff: (cursorDiff: number) => ({ cursorDiff }),
        handleSeek: (newX: number, shouldSeek: boolean = true) => ({ newX, shouldSeek }),
        handleMove: (event: InteractEvent) => ({ event }),
        handleUp: (event: InteractEvent) => ({ event }),
        handleDown: (event: ReactInteractEvent) => ({ event }),
        handleClick: (event: ReactInteractEvent) => ({ event }),
        setSlider: (ref: MutableRefObject<HTMLDivElement | null>) => ({ ref }),
        setThumb: (ref: MutableRefObject<HTMLDivElement | null>) => ({ ref }),
        debouncedSetTime: (time: number) => ({ time }),
        endSeeking: true,
    }),
    reducers({
        thumbLeftPos: [
            -THUMB_OFFSET,
            {
                setThumbLeftPos: (_, { thumbLeftPos }) => {
                    // we receive this number to many decimal places, so we round it to 1 decimal place
                    // since otherwise we render dependent components
                    // thousands of times more than we need to
                    return parseFloat(thumbLeftPos.toFixed(1))
                },
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
    }),
    selectors({
        endTimeMs: [
            (selectors) => [selectors.sessionPlayerData],
            (sessionPlayerData) => {
                return sessionPlayerData?.durationMs ?? 0
            },
        ],

        bufferPercent: [
            (selectors) => [selectors.sessionPlayerData],
            (sessionPlayerData) => {
                if (sessionPlayerData?.bufferedToTime && sessionPlayerData?.segments && sessionPlayerData?.durationMs) {
                    // we calculate this number to many decimal places, so we round it to 1 decimal place
                    // since otherwise we render dependent components
                    // thousands of times more than we need to
                    return parseFloat(
                        (100 * (sessionPlayerData?.bufferedToTime / sessionPlayerData.durationMs)).toFixed(1)
                    )
                }
                return 0
            },
        ],
        scrubbingTime: [
            (selectors) => [selectors.thumbLeftPos, selectors.slider, selectors.sessionPlayerData],
            (thumbLeftPos, slider, sessionPlayerData) => {
                if (thumbLeftPos && slider && sessionPlayerData?.durationMs) {
                    return ((thumbLeftPos + THUMB_OFFSET) / slider.offsetWidth) * sessionPlayerData.durationMs
                }
                return 0
            },
        ],
        scrubbingTimeSeconds: [
            (selectors) => [selectors.scrubbingTime],
            (scrubbingTime) => Math.floor(scrubbingTime / 1000),
        ],
    }),
    listeners(({ values, actions }) => ({
        setCurrentTimestamp: () => {
            if (!values.slider) {
                return
            }
            // Don't update thumb position if seekbar logic is already seeking and setting the thumb position.
            // Except in one case when the updated thumb position is at the start. This happens when the user
            // scrubs to the end of the recording while playing, and then the player loop restarts the recording.
            if (!values.isSeeking) {
                const xValue =
                    ((values.currentPlayerTime ?? 0) / values.sessionPlayerData.durationMs) * values.slider.offsetWidth
                actions.setThumbLeftPos(xValue - THUMB_OFFSET, false)
            }
        },

        setThumbLeftPos: ({ thumbLeftPos, shouldSeek }) => {
            if (!values.slider) {
                return
            }
            if (shouldSeek) {
                const playerTime =
                    ((thumbLeftPos + THUMB_OFFSET) / values.slider.offsetWidth) * values.sessionPlayerData.durationMs
                actions.seekToTime(playerTime)
            }
        },
        handleSeek: ({ newX, shouldSeek }) => {
            const end = values.slider?.offsetWidth ?? 0
            actions.setThumbLeftPos(clamp(newX, 0, end) - THUMB_OFFSET, shouldSeek)
            actions.endSeeking()
        },
        handleMove: ({ event }) => {
            if (!values.slider) {
                return
            }
            actions.startScrub()
            const newX = getXPos(event) - values.cursorDiff - values.slider.getBoundingClientRect().left
            actions.handleSeek(newX, false)
        },
        handleUp: ({ event }) => {
            document.removeEventListener('touchmove', actions.handleMove)
            document.removeEventListener('touchend', actions.handleUp)
            document.removeEventListener('mousemove', actions.handleMove)
            document.removeEventListener('mouseup', actions.handleUp)

            if (!values.slider) {
                return
            }
            const newX = getXPos(event) - values.cursorDiff - values.slider.getBoundingClientRect().left
            actions.handleSeek(newX)
            actions.endScrub()
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
    })),
])

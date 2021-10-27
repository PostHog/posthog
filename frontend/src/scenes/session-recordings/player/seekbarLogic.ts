import { MutableRefObject as ReactMutableRefObject } from 'react'
import { kea } from 'kea'
import { seekbarLogicType } from './seekbarLogicType'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { clamp } from 'lib/utils'
import { playerMetaData } from 'rrweb/typings/types'
import { SessionPlayerTime } from '~/types'
import {
    convertValueToX,
    convertXToValue,
    getXPos,
    InteractEvent,
    ReactInteractEvent,
    THUMB_OFFSET,
    THUMB_SIZE,
    TOUCH_ENABLED,
} from 'scenes/session-recordings/player/seekbarUtils'

export const seekbarLogic = kea<seekbarLogicType>({
    connect: {
        values: [sessionRecordingPlayerLogic, ['meta', 'zeroOffsetTime', 'time']],
        actions: [
            sessionRecordingPlayerLogic,
            ['seek', 'clearLoadingState', 'setScrub', 'setCurrentTime', 'setRealTime'],
        ],
    },
    actions: {
        setThumbLeftPos: (thumbLeftPos: number, shouldSeek: boolean) => ({ thumbLeftPos, shouldSeek }),
        setCursorDiff: (cursorDiff: number) => ({ cursorDiff }),
        handleSeek: (newX: number, shouldSeek: boolean = true) => ({ newX, shouldSeek }),
        handleMove: (event: InteractEvent) => ({ event }),
        handleUp: (event: InteractEvent) => ({ event }),
        handleDown: (event: ReactInteractEvent) => ({ event }),
        handleClick: (event: ReactInteractEvent) => ({ event }),
        setSlider: (ref: ReactMutableRefObject<HTMLDivElement | null>) => ({ ref }),
        setThumb: (ref: ReactMutableRefObject<HTMLDivElement | null>) => ({ ref }),
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
    },
    selectors: {
        bufferPercent: [
            (selectors) => [selectors.zeroOffsetTime, selectors.meta],
            (time: SessionPlayerTime, meta: playerMetaData) =>
                (Math.max(time.lastBuffered, time.current) * 100) / meta.totalTime,
        ],
    },
    listeners: ({ values, actions }) => ({
        setCurrentTime: async () => {
            if (!values.slider) {
                return
            }
            // Don't update thumb position if seekbar logic is already seeking and setting the thumb position
            if (!values.isSeeking) {
                actions.setThumbLeftPos(
                    convertValueToX(
                        values.zeroOffsetTime.current,
                        values.slider.offsetWidth,
                        0,
                        values.meta.totalTime
                    ) - THUMB_OFFSET,
                    false
                )
            }
        },
        debouncedSetTime: async ({ time }, breakpoint) => {
            await breakpoint(5)
            actions.setRealTime(time)
        },
        setThumbLeftPos: ({ thumbLeftPos, shouldSeek }) => {
            // Debounce seeking so that scrubbing doesn't sent a bajillion requests.
            if (!values.slider) {
                return
            }

            const time = convertXToValue(
                thumbLeftPos + THUMB_OFFSET,
                values.slider.offsetWidth,
                values.meta.startTime,
                values.meta.endTime
            )

            // If it shouldn't seek, the least we can do is set the time
            if (!shouldSeek) {
                actions.debouncedSetTime(time)
            } else {
                actions.seek(time)
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
            actions.setScrub()
            const newX = getXPos(event) - values.cursorDiff - values.slider.getBoundingClientRect().left
            actions.handleSeek(newX, false)
        },
        handleUp: ({ event }) => {
            if (!values.slider) {
                return
            }
            const newX = getXPos(event) - values.cursorDiff - values.slider.getBoundingClientRect().left
            actions.handleSeek(newX)
            actions.clearLoadingState()

            if (TOUCH_ENABLED) {
                document.removeEventListener('touchmove', actions.handleMove)
                document.removeEventListener('touchend', actions.handleUp)
            } else {
                document.removeEventListener('mousemove', actions.handleMove)
                document.removeEventListener('mouseup', actions.handleUp)
            }
        },
        handleDown: ({ event }) => {
            if (!values.thumb) {
                return
            }

            actions.setScrub()
            const xPos = getXPos(event)
            let diffFromThumb = xPos - values.thumb.getBoundingClientRect().left - THUMB_OFFSET
            // If click is too far from thumb, move thumb to click position
            if (Math.abs(diffFromThumb) > THUMB_SIZE) {
                diffFromThumb = -THUMB_OFFSET
            }
            actions.setCursorDiff(diffFromThumb)

            if (TOUCH_ENABLED) {
                document.addEventListener('touchmove', actions.handleMove)
                document.addEventListener('touchend', actions.handleUp)
            } else {
                document.addEventListener('mousemove', actions.handleMove)
                document.addEventListener('mouseup', actions.handleUp)
            }
        },
    }),
    events: ({ actions, values }) => ({
        afterMount: () => {
            window.addEventListener('resize', () => actions.setCurrentTime(values.time.current))
        },
        afterUnmount: () => {
            window.removeEventListener('resize', () => actions.setCurrentTime(values.time.current))
        },
    }),
})

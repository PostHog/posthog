import { MouseEvent as ReactMouseEvent, MutableRefObject as ReactMutableRefObject } from 'react'
import { kea } from 'kea'
import { seekbarLogicType } from './seekbarLogicType'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { clamp } from 'lib/utils'
import { playerMetaData } from 'rrweb/typings/types'
import { SessionPlayerTime } from '~/types'
const THUMB_SIZE = 14
const THUMB_OFFSET = THUMB_SIZE / 2

const convertXToValue = (xPos: number, containerWidth: number, start: number, end: number): number => {
    return (xPos / containerWidth) * (end - start) + start
}
const convertValueToX = (value: number, containerWidth: number, start: number, end: number): number => {
    return (containerWidth * (value - start)) / (end - start)
}

export const seekbarLogic = kea<seekbarLogicType>({
    connect: {
        values: [sessionRecordingPlayerLogic, ['meta', 'zeroOffsetTime']],
        actions: [sessionRecordingPlayerLogic, ['seek', 'clearLoadingState', 'setScrub', 'setCurrentTime']],
    },
    actions: {
        setThumbLeftPos: (thumbLeftPos: number, shouldSeek: boolean) => ({ thumbLeftPos, shouldSeek }),
        setCursorDiff: (cursorDiff: number) => ({ cursorDiff }),
        handleSeek: (newX: number) => ({ newX }),
        handleMouseMove: (event: MouseEvent) => ({ event }),
        handleMouseUp: (event: MouseEvent) => ({ event }),
        handleMouseDown: (event: ReactMouseEvent<HTMLDivElement, MouseEvent>) => ({ event }),
        handleMouseClick: (event: ReactMouseEvent<HTMLDivElement, MouseEvent>) => ({ event }),
        setSlider: (ref: ReactMutableRefObject<HTMLDivElement | null>) => ({ ref }),
        setThumb: (ref: ReactMutableRefObject<HTMLDivElement | null>) => ({ ref }),
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
            actions.setThumbLeftPos(
                convertValueToX(values.zeroOffsetTime.current, values.slider.offsetWidth, 0, values.meta.totalTime) -
                    THUMB_OFFSET,
                false
            )
        },
        setThumbLeftPos: async ({ thumbLeftPos, shouldSeek }, breakpoint) => {
            // Debounce seeking so that scrubbing doesn't sent a bajillion requests.
            if (!values.slider || !shouldSeek) {
                return
            }
            actions.seek(
                convertXToValue(
                    thumbLeftPos + THUMB_OFFSET,
                    values.slider.offsetWidth,
                    values.meta.startTime,
                    values.meta.endTime
                )
            )
            breakpoint()
        },
        handleSeek: ({ newX }) => {
            const end = values.slider?.offsetWidth ?? 0
            actions.setThumbLeftPos(clamp(newX, 0, end) - THUMB_OFFSET, true)
        },
        handleMouseMove: ({ event }) => {
            if (!values.slider) {
                return
            }
            actions.setScrub()
            const newX = event.clientX - values.cursorDiff - values.slider.getBoundingClientRect().left
            actions.handleSeek(newX)
        },
        handleMouseUp: ({ event }) => {
            if (!values.slider) {
                return
            }

            const newX = event.clientX - values.cursorDiff - values.slider.getBoundingClientRect().left
            actions.handleSeek(newX)
            actions.clearLoadingState()
            document.removeEventListener('mouseup', actions.handleMouseUp)
            document.removeEventListener('mousemove', actions.handleMouseMove)
        },
        handleMouseDown: ({ event }) => {
            if (!values.thumb) {
                return
            }
            actions.setScrub()
            actions.setCursorDiff(event.clientX - values.thumb.getBoundingClientRect().left - THUMB_OFFSET)

            document.addEventListener('mousemove', actions.handleMouseMove)
            document.addEventListener('mouseup', actions.handleMouseUp)
        },
        handleMouseClick: ({ event }) => {
            if (!values.slider) {
                return
            }
            // jump thumb to click position
            const newX = event.clientX - values.slider.getBoundingClientRect().left
            actions.handleSeek(newX)
        },
    }),
})

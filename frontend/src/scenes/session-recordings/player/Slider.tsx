import './Slider.scss'
import React, { useEffect, useRef, useState } from 'react'
import { useDebouncedCallback } from 'use-debounce/lib'
import { clamp } from 'lib/utils'
import { useActions, useValues } from 'kea'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

// enum SectionType {
//     INACTIVE = 'inactive',
//     DEFAULT = 'default',
// }

// interface RangeSection {
//     start: number
//     end: number
//     type: SectionType
// }
//
// interface SliderProps {
//     sections?: RangeSection[]
// }

const convertXToValue = (xPos: number, containerWidth: number, start: number, end: number): number => {
    return (xPos / containerWidth) * (end - start) + start
}

export function Slider(): JSX.Element {
    const sliderRef = useRef<HTMLDivElement | null>(null)
    const thumbRef = useRef<HTMLDivElement | null>(null)
    const [thumbLeftPos, setThumbPos] = useState<number>(-6) // half of thumb width
    const diff = useRef<number>()

    const { zeroOffsetTime, meta, time, currentPlayerState } = useValues(sessionRecordingPlayerLogic)
    const { setScrub, clearLoadingState, seek } = useActions(sessionRecordingPlayerLogic)

    // Debounce seeking so that scrubbing doesn't sent a bajillion requests.
    const seekDebounced = useDebouncedCallback((nextTime) => seek(nextTime), 500)

    useEffect(() => {
        if (!sliderRef.current) {
            return
        }
        const nextTime = convertXToValue(thumbLeftPos + 6, sliderRef.current.offsetWidth, meta.startTime, meta.endTime)
        seekDebounced(nextTime)
    }, [thumbLeftPos])

    const handleSeek = (_newX: number): void => {
        const end = sliderRef.current?.offsetWidth ?? 0
        const newX = clamp(_newX, 0, end)
        setThumbPos(newX - 6)
    }

    const handleMouseMove = (event: MouseEvent): void => {
        if (!diff.current || !sliderRef.current) {
            return
        }
        const newX = event.clientX - diff.current - sliderRef.current.getBoundingClientRect().left
        handleSeek(newX)
    }

    const handleMouseUp = (): void => {
        clearLoadingState()
        document.removeEventListener('mouseup', handleMouseUp)
        document.removeEventListener('mousemove', handleMouseMove)
    }

    const handleMouseDown = (event: React.MouseEvent<HTMLDivElement, MouseEvent>): void => {
        if (!thumbRef.current) {
            return
        }
        setScrub()
        diff.current = event.clientX - thumbRef.current.getBoundingClientRect().left - 6

        document.addEventListener('mousemove', handleMouseMove)
        document.addEventListener('mouseup', handleMouseUp)
    }

    const handleClick = (event: React.MouseEvent<HTMLDivElement, MouseEvent>): void => {
        if (!sliderRef.current) {
            return
        }
        // jump thumb to click position
        const newX = event.clientX - sliderRef.current.getBoundingClientRect().left
        handleSeek(newX)
    }

    const bufferPercent = (Math.max(zeroOffsetTime.lastBuffered, zeroOffsetTime.current) * 100) / meta.totalTime

    console.log('CURRENT STATE', currentPlayerState)
    console.log('PROPS', time, zeroOffsetTime, meta)

    return (
        <div className="rrweb-controller-slider" ref={sliderRef} onClick={handleClick}>
            <div className="slider" />
            <div className="thumb" ref={thumbRef} onMouseDown={handleMouseDown} style={{ left: thumbLeftPos }} />
            <div className="current-bar" style={{ width: `${thumbLeftPos}px` }} />
            <div className="buffer-bar" style={{ width: `${bufferPercent}%` }} />
        </div>
    )
}

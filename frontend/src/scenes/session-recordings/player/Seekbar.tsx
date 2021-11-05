import './Seekbar.scss'
import React, { useEffect, useRef, useState } from 'react'
import { useActions, useValues } from 'kea'
import clsx from 'clsx'
import { seekbarLogic } from 'scenes/session-recordings/player/seekbarLogic'
import { SeekbarEventType } from '~/types'

function Tick({ marker }: { marker: SeekbarEventType }): JSX.Element {
    const [hovering, setHovering] = useState(false)
    const { handleTickClick } = useActions(seekbarLogic)
    return (
        <div
            className="tick-hover-box"
            style={{ left: `calc(${marker.percentage}% - 2px)` }}
            onClick={(e) => {
                e.stopPropagation()
                handleTickClick(marker.timestamp)
            }}
            onMouseEnter={(e) => {
                e.stopPropagation()
                setHovering(true)
            }}
            onMouseLeave={(e) => {
                e.stopPropagation()
                setHovering(false)
            }}
        >
            <div className={clsx('tick-info', { show: hovering })}>{marker.event}</div>
            <div className="tick-marker" />
            <div className={clsx('tick-thumb', { big: hovering })} />
        </div>
    )
}

export function Seekbar(): JSX.Element {
    const sliderRef = useRef<HTMLDivElement | null>(null)
    const thumbRef = useRef<HTMLDivElement | null>(null)
    const { handleDown, setSlider, setThumb } = useActions(seekbarLogic)
    const { thumbLeftPos, bufferPercent, markersWithPositions } = useValues(seekbarLogic)

    // Workaround: Something with component and logic mount timing that causes slider and thumb
    // reducers to be undefined.
    useEffect(() => {
        if (sliderRef.current && thumbRef.current) {
            setSlider(sliderRef)
            setThumb(thumbRef)
        }
    }, [sliderRef.current, thumbRef.current])

    return (
        <div className="rrweb-controller-slider">
            <div className="slider" ref={sliderRef} onMouseDown={handleDown} onTouchStart={handleDown}>
                <div className="slider-bar" />
                <div className="thumb" ref={thumbRef} style={{ transform: `translateX(${thumbLeftPos}px)` }} />
                <div className="current-bar" style={{ width: `${thumbLeftPos}px` }} />
                <div className="buffer-bar" style={{ width: `calc(${bufferPercent}% - 2px)` }} />
            </div>
            <div className="ticks">
                {markersWithPositions.map((marker) => (
                    <Tick key={marker.id} marker={marker} />
                ))}
            </div>
        </div>
    )
}

import './Seekbar.scss'
import React, { useEffect, useRef } from 'react'
import { useActions, useValues } from 'kea'
import { seekbarLogic } from 'scenes/session-recordings/player/seekbarLogic'

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

    console.log('EVENTS', markersWithPositions.length)

    return (
        <div className="rrweb-controller-slider" ref={sliderRef} onMouseDown={handleDown} onTouchStart={handleDown}>
            <div className="slider" />
            <div className="thumb" ref={thumbRef} style={{ transform: `translateX(${thumbLeftPos}px)` }} />
            <div className="current-bar" style={{ width: `${thumbLeftPos}px` }} />
            <div className="buffer-bar" style={{ width: `${bufferPercent}%` }} />
            <div className="ticks">
                {markersWithPositions.map((marker) => (
                    <div className="tick" key={marker.id} style={{ width: `${marker.percentage}%` }}>
                        <div className="tick-thumb" />
                    </div>
                ))}
            </div>
        </div>
    )
}

import { useEffect, useState } from 'react'

function getCoords(e) {
    if (e && e.touches && e.touches[0]) {
        return [e.touches[0].clientX, e.touches[0].clientY]
    }
    return [e.clientX, e.clientY]
}

function diffInCoords(e, initialCoords) {
    const coords = getCoords(e)
    return Math.abs(coords[0] - initialCoords[0]) + Math.abs(coords[1] - initialCoords[1])
}

export function useLongPress(
    callback = () => {},
    { ms = 300, pixelDistance = 10, touch = true, click = true, exclude = '' }
) {
    const [startLongPress, setStartLongPress] = useState(false)
    const [initialCoords, setInitialCoords] = useState(null)

    useEffect(() => {
        let timerId
        if (startLongPress) {
            timerId = setTimeout(() => {
                callback()
                stop()
            }, ms)
        }

        return () => {
            clearTimeout(timerId)
        }
    }, [callback, ms, startLongPress])

    function start(e) {
        if (exclude && e.target.matches(exclude)) {
            return
        }
        setInitialCoords(getCoords(e))
        setStartLongPress(true)
    }

    function move(e) {
        if (initialCoords && diffInCoords(e, initialCoords) > pixelDistance) {
            setInitialCoords(null)
            setStartLongPress(false)
        }
    }

    function stop() {
        setInitialCoords(null)
        setStartLongPress(false)
    }

    let events = {}

    if (touch) {
        events.onTouchStart = start
        events.onTouchMove = move
        events.onTouchEnd = stop
    }

    if (click) {
        events.onMouseDown = start
        events.onMouseMove = move
        events.onMouseUp = stop
        events.onMouseLeave = stop
    }

    return events
}

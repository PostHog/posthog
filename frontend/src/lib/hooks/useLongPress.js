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

/*
    Use: - const eventHandlers = useLongPress(callback, opts)
         - render(<div {...eventHandlers}></div>)

    Opts: - ms = 300           - number of ms before registered as long press
          - clickMs = null     - if delay is between 0 < clickMs < x < ms --> count it as a click
          - pixelDistance = 10 - pixels the mouse can move so that we still count it as a press
          - touch = true       - support touch actions
          - click = true       - support click actions
          - exclude = ''       - selector for when to NOT start long-pressing
 */
export function useLongPress(
    callback = (clicked = false, ms = null) => {}, // eslint-disable-line
    { ms = 300, pixelDistance = 10, touch = true, click = true, exclude = '', clickMs = null }
) {
    const [startLongPress, setStartLongPress] = useState(null)
    const [initialCoords, setInitialCoords] = useState(null)

    useEffect(() => {
        let timerId
        if (startLongPress && ms) {
            timerId = setTimeout(() => {
                callback(false, window.performance.now() - startLongPress, initialCoords)
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
        if (e.button && e.button > 1) {
            return
        }
        if (e.ctrlKey || e.altKey || e.metaKey) {
            return
        }
        setInitialCoords(getCoords(e))
        setStartLongPress(window.performance.now())
    }

    function move(e) {
        if (initialCoords && diffInCoords(e, initialCoords) > pixelDistance) {
            setInitialCoords(null)
            setStartLongPress(null)
        }
    }

    function stopClick() {
        if (clickMs && startLongPress) {
            const timeDiff = window.performance.now() - startLongPress
            if (timeDiff >= clickMs && (!ms || timeDiff < ms)) {
                callback(true, timeDiff)
            }
        }
        setInitialCoords(null)
        setStartLongPress(null)
    }

    function stop() {
        setInitialCoords(null)
        setStartLongPress(null)
    }

    let events = {}

    if (touch) {
        events.onTouchStart = start
        events.onTouchMove = move
        events.onTouchEnd = stopClick
    }

    if (click) {
        events.onMouseDown = start
        events.onMouseMove = move
        events.onMouseUp = stopClick
        events.onMouseLeave = stop
    }

    return events
}

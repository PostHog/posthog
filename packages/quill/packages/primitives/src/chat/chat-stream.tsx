import * as React from 'react'

import './chat-stream.css'
import { cn } from '../lib/utils'

/**
 * Output arriving live, in a window that follows it — an agent thinking out loud, a log tailing, a
 * response streaming in.
 *
 * `pinned` is the whole API. While it's true the window stays anchored to the newest content: the
 * stream slides up as it outgrows the cap, older lines dissolve off the top edge, and the reader
 * can't scroll (there's nothing below to scroll to). Turn it off when the output stops and the
 * window becomes an ordinary scroll area, left exactly where the pin ended — on the last thing
 * said — for the reader to scroll back through.
 *
 * The pin is a transform, not a scroll. A scroll jump teleports the older lines; a transform can
 * ease, and it doesn't affect layout — so the window still sizes to its content, capped by
 * `--quill-chat-stream-max-height` (default `11.25rem`).
 *
 * It brings no chrome and no rail: drop it wherever the output belongs — a `ThreadItemBody` in a
 * feed, a `ChatMarker`'s `body` behind a "Thinking…" summary — and let the container frame it.
 */
type ChatStreamProps = React.ComponentProps<'div'> & {
    /** Follow the newest content. Turn it off when the output stops and the reader takes over. */
    pinned?: boolean
}

function ChatStream({ pinned = false, className, children, ...props }: ChatStreamProps): React.ReactElement {
    const viewportRef = React.useRef<HTMLDivElement>(null)
    const streamRef = React.useRef<HTMLDivElement>(null)

    /*
     * `pinned` is what the caller wants; `following` is what the window is doing. Releasing lags the
     * prop by one slide.
     *
     * The last line almost always lands in the same render that ends the output — the final token
     * arrives and the thing is done. Releasing on that render would cut the slide that carries the
     * line into view, so the stream teleports to the end instead of easing there. Following through
     * the final slide, then handing over, is the difference between the stream stopping and the
     * stream snapping. Re-pinning has nothing to finish, so it takes effect immediately.
     */
    const [following, setFollowing] = React.useState(pinned)

    // Written straight to the DOM rather than through state: this runs on every scroll frame and on
    // every line, and a re-render per frame is how you drop them.
    const sync = React.useCallback(() => {
        const viewport = viewportRef.current
        const stream = streamRef.current
        if (!viewport || !stream) {
            return
        }
        const setFade = (top: boolean, bottom: boolean): void => {
            viewport.toggleAttribute('data-fade-top', top)
            viewport.toggleAttribute('data-fade-bottom', bottom)
        }
        if (following) {
            // A transform doesn't affect layout, so the viewport still sizes to the stream (capped),
            // and the overflow is exactly what we slide by.
            const overflow = Math.max(0, stream.offsetHeight - viewport.clientHeight)
            stream.style.setProperty('--quill-chat-stream-offset', `${-overflow}px`)
            // Nothing sits below the newest line, so only the top edge needs softening.
            setFade(overflow > 0, false)
            return
        }
        stream.style.setProperty('--quill-chat-stream-offset', '0px')
        setFade(viewport.scrollTop > 1, viewport.scrollTop + viewport.clientHeight < viewport.scrollHeight - 1)
    }, [following])

    // Content arrives a line (or a token) at a time, resizing the stream rather than re-rendering
    // this component — so watch the box, not the children.
    React.useLayoutEffect(() => {
        const stream = streamRef.current
        if (!stream) {
            return
        }
        const observer = new ResizeObserver(sync)
        observer.observe(stream)
        return () => observer.disconnect()
    }, [sync])

    // Re-pin at once; release only once the slide in flight has landed.
    React.useEffect(() => {
        if (pinned) {
            setFollowing(true)
            return
        }
        const stream = streamRef.current
        if (!following || !stream) {
            return
        }
        let released = false
        const release = (): void => {
            if (released) {
                return
            }
            released = true
            setFollowing(false)
        }
        const onEnd = (event: TransitionEvent): void => {
            if (event.propertyName === 'translate') {
                release()
            }
        }
        stream.addEventListener('transitionend', onEnd)
        // A slide that never starts fires no `transitionend` — the offset may not have changed, or
        // reduced motion may have removed the transition entirely. Read the duration off the element
        // rather than restating it here, so this can't drift from the CSS.
        const duration = parseFloat(getComputedStyle(stream).transitionDuration) * 1000 || 0
        const fallback = setTimeout(release, duration + 50)
        return () => {
            stream.removeEventListener('transitionend', onEnd)
            clearTimeout(fallback)
        }
    }, [pinned, following])

    const wasFollowing = React.useRef(following)

    React.useLayoutEffect(() => {
        const viewport = viewportRef.current
        const stream = streamRef.current
        // Letting go must not move anything: the reader is looking at the tail, and that's where the
        // output ended. So hand the pin's transform over to the equivalent scroll offset — the two
        // describe the same position, so the swap is invisible, and afterwards the reader can scroll
        // back through it.
        //
        // Both in one frame with the transition suppressed. Left to animate, the transform would ease
        // back to 0 while the scroll jumped instantly, and the content would lurch by the overflow in
        // each direction before settling.
        if (wasFollowing.current && !following && viewport && stream) {
            const overflow = Math.max(0, stream.offsetHeight - viewport.clientHeight)
            const transition = stream.style.transition
            stream.style.transition = 'none'
            stream.style.setProperty('--quill-chat-stream-offset', '0px')
            viewport.scrollTop = overflow
            void stream.offsetHeight
            stream.style.transition = transition
        }
        wasFollowing.current = following
        sync()
    }, [following, sync])

    return (
        <div
            ref={viewportRef}
            data-quill
            data-slot="stream"
            data-pinned={following || undefined}
            onScroll={sync}
            className={cn('quill-chat-stream', className)}
            {...props}
        >
            <div ref={streamRef} data-slot="stream-lines" className="quill-chat-stream__lines">
                {children}
            </div>
        </div>
    )
}

/** One line of output. Reveals itself as it arrives, while the stream is pinned. */
function ChatStreamLine({ className, ...props }: React.ComponentProps<'p'>): React.ReactElement {
    return <p data-slot="stream-line" className={cn('quill-chat-stream__line', className)} {...props} />
}

export { ChatStream, ChatStreamLine }

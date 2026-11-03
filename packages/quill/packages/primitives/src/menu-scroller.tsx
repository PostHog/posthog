import * as React from 'react'

/**
 * The scrolling list of a menu popup, with an edge fade while there is more to scroll.
 *
 * The fade runs on a scroll-driven animation. When the list shrinks until it no longer scrolls, such as a filtered
 * menu going from many rows to one, Chrome keeps the last fade and covers the rows at the edge. Restarting the
 * animation after each change of rows clears it.
 */
function MenuScroller({ children }: { children: React.ReactNode }): React.ReactElement {
    const ref = React.useRef<HTMLDivElement>(null)

    React.useEffect(() => {
        const scroller = ref.current
        if (!scroller) {
            return
        }
        let frame = 0
        const observer = new MutationObserver(() => {
            cancelAnimationFrame(frame)
            frame = requestAnimationFrame(() => {
                if (scroller.scrollHeight > scroller.clientHeight) {
                    return
                }
                scroller.style.animation = 'none'
                void scroller.offsetHeight
                scroller.style.animation = ''
            })
        })
        observer.observe(scroller, { childList: true, subtree: true })
        return () => {
            observer.disconnect()
            cancelAnimationFrame(frame)
        }
    }, [])

    return (
        <div ref={ref} className="quill-menu__scroller scroll-mask-y-4 scroll-py-4">
            {children}
        </div>
    )
}

export { MenuScroller }

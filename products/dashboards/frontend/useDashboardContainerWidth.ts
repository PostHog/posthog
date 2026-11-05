import { RefObject, useEffect, useLayoutEffect, useRef, useState } from 'react'

export function useDashboardContainerWidth(): { width: number; containerRef: RefObject<HTMLDivElement> } {
    const containerRef = useRef<HTMLDivElement>(null)
    const [width, setWidth] = useState(1280)

    useLayoutEffect(() => {
        const container = containerRef.current
        if (!container) {
            return
        }

        container.classList.add('dashboard-container-width-changing')
        let frame = requestAnimationFrame(() => {
            frame = requestAnimationFrame(() => container.classList.remove('dashboard-container-width-changing'))
        })
        return () => {
            cancelAnimationFrame(frame)
            container.classList.remove('dashboard-container-width-changing')
        }
    }, [width])

    useEffect(() => {
        const container = containerRef.current
        if (!container) {
            return
        }

        let pendingWidth = Math.round(container.getBoundingClientRect().width)
        setWidth(pendingWidth)
        let timer: ReturnType<typeof setTimeout> | undefined
        let deferredDuringResize = false
        const commitWidth = (): void => {
            if (document.body.classList.contains('is-resizing')) {
                deferredDuringResize = true
                timer = setTimeout(commitWidth, 16)
                return
            }
            setWidth(Math.round(pendingWidth))
            deferredDuringResize = false
        }
        const observer = new ResizeObserver(([entry]) => {
            if (!entry) {
                return
            }

            const nextWidth = Math.round(entry.contentRect.width)
            if (nextWidth === pendingWidth) {
                return
            }

            // Commit after resize settles so sidebar drags do not render every dashboard tile each frame.
            clearTimeout(timer)
            pendingWidth = nextWidth
            deferredDuringResize ||= document.body.classList.contains('is-resizing')
            timer = setTimeout(commitWidth, deferredDuringResize ? 16 : 100)
        })
        observer.observe(container)

        return () => {
            observer.disconnect()
            clearTimeout(timer)
        }
    }, [])

    return { width, containerRef }
}

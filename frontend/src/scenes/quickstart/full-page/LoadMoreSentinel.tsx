import { useEffect, useRef } from 'react'

export function LoadMoreSentinel({ onVisible }: { onVisible: () => void }): JSX.Element {
    const ref = useRef<HTMLDivElement | null>(null)

    useEffect(() => {
        const element = ref.current
        if (!element) {
            return
        }
        const observer = new IntersectionObserver(
            (entries) => {
                if (entries.some((entry) => entry.isIntersecting)) {
                    onVisible()
                }
            },
            { rootMargin: '400px' }
        )
        observer.observe(element)
        return () => observer.disconnect()
    }, [onVisible])

    return <div ref={ref} className="h-px" />
}

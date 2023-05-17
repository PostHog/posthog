import { RefObject, useEffect, useState } from 'react'

export function useIntersectionObserver(
    elementRef: RefObject<HTMLElement>,
    observerOptions?: IntersectionObserverInit,
    callback?: (entry: IntersectionObserverEntry) => void
): IntersectionObserverEntry | undefined {
    const [entry, setEntry] = useState<IntersectionObserverEntry>()

    useEffect(() => {
        if (!window.IntersectionObserver || !elementRef?.current) {
            return // Skip if IntersectionObserver or node are not available
        }
        const observer = new IntersectionObserver(([entry]) => {
            setEntry(entry)
            callback?.(entry)
        }, observerOptions)
        observer.observe(elementRef.current)
        return () => observer.disconnect()
    }, [
        elementRef?.current,
        observerOptions && Array.isArray(observerOptions.threshold)
            ? observerOptions.threshold.join(',')
            : observerOptions?.threshold,
        observerOptions?.root,
        observerOptions?.rootMargin,
    ])

    return entry
}

export default useIntersectionObserver

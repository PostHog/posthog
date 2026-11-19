import { RefObject, useEffect, useRef, useState } from 'react'

export function useElementSize<T extends HTMLElement>(): { ref: RefObject<T>; width: number; height: number } {
    const ref = useRef<T>(null)
    const [size, setSize] = useState({ width: 0, height: 0 })

    useEffect(() => {
        const element = ref.current
        if (!element) {
            return
        }
        const observer = new ResizeObserver(([entry]) => {
            const { width, height } = entry.contentRect
            setSize((previous) =>
                previous.width === width && previous.height === height ? previous : { width, height }
            )
        })
        observer.observe(element)
        return () => observer.disconnect()
    }, [])

    return { ref, width: size.width, height: size.height }
}

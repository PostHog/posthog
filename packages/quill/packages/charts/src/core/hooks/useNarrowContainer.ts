import { useEffect, useRef, useState } from 'react'

interface NarrowContainerState {
    /** Attach to the element whose width decides narrowness. */
    ref: React.RefObject<HTMLDivElement>
    /** True once the observed element measures below the threshold. */
    isNarrow: boolean
}

/** Tracks whether a container is narrower than `threshold` px. Initial state is not-narrow and the
 *  ResizeObserver corrects on its guaranteed first delivery, so a narrow container renders wide for
 *  one commit — the observer's layout-size entry is used rather than getBoundingClientRect so
 *  ancestor transform animations (e.g. a modal opening) don't misread the width. */
export function useNarrowContainer(threshold: number): NarrowContainerState {
    const ref = useRef<HTMLDivElement | null>(null)
    const [isNarrow, setIsNarrow] = useState(false)

    useEffect(() => {
        const element = ref.current
        if (!element) {
            return
        }
        const observer = new ResizeObserver((entries) => {
            // jsdom's ResizeObserver stub delivers neither borderBoxSize nor contentRect — fall
            // back to the (mocked) bounding rect there.
            const entry = entries[entries.length - 1]
            const width = entry?.borderBoxSize?.[0]?.inlineSize ?? entry?.contentRect?.width
            setIsNarrow((prev) => {
                const next = (width ?? element.getBoundingClientRect().width) < threshold
                return prev === next ? prev : next
            })
        })
        observer.observe(element)
        return () => observer.disconnect()
    }, [threshold])

    return { ref, isNarrow }
}

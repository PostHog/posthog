// DVD screensaver bouncing animation hook
// Adapted from https://github.com/samuelweckstrom/react-dvd-screensaver (MIT)

import { useEffect, useRef, useState } from 'react'

interface DvdOptions {
    speed?: number
    impactCallback?: (count: number) => void
    onCornerHit?: () => void
    paused?: boolean
}

interface AnimationState {
    animationFrameId: number
    impactCount: number
    isPosXIncrement: boolean
    isPosYIncrement: boolean
    lastTimestamp: number
    positionX: number
    positionY: number
}

export function useDvdScreensaver<T extends HTMLElement = HTMLDivElement>(
    options?: Partial<DvdOptions>
): {
    containerRef: React.RefObject<T | null>
    elementRef: React.RefObject<T | null>
    impactCount: number
} {
    const optionsRef = useRef(options)
    optionsRef.current = options

    const animationState = useRef<AnimationState>({
        animationFrameId: 0,
        impactCount: 0,
        isPosXIncrement: true,
        isPosYIncrement: true,
        lastTimestamp: 0,
        positionX: 0,
        positionY: 0,
    })

    const animateFnRef = useRef<((timestamp: number) => void) | undefined>(undefined)
    const elementRef = useRef<T | null>(null)
    const containerRef = useRef<T | null>(null)
    const [impactCount, setImpactCount] = useState(0)

    useEffect(() => {
        const element = elementRef.current
        const container = (containerRef.current as HTMLElement | null) ?? element?.parentElement

        function updatePosition(
            containerSpan: number,
            delta: number,
            elementSpan: number,
            prevPos: number,
            toggleKey: 'isPosXIncrement' | 'isPosYIncrement'
        ): { pos: number; hit: boolean } {
            const boundary = Math.max(0, containerSpan - elementSpan)
            let newPos = prevPos + (animationState.current[toggleKey] ? delta : -delta)
            let hit = false
            if (newPos <= 0 || newPos >= boundary) {
                animationState.current[toggleKey] = !animationState.current[toggleKey]
                animationState.current.impactCount += 1
                setImpactCount(animationState.current.impactCount)
                optionsRef.current?.impactCallback?.(animationState.current.impactCount)
                newPos = Math.max(0, Math.min(newPos, boundary))
                hit = true
            }
            return { pos: newPos, hit }
        }

        function animate(timestamp: number): void {
            const el = elementRef.current
            const ctr = (containerRef.current as HTMLElement | null) ?? el?.parentElement

            if (el && ctr) {
                const last = animationState.current.lastTimestamp
                const elapsed = last ? Math.min(timestamp - last, 50) : 1000 / 60
                animationState.current.lastTimestamp = timestamp

                const speed = optionsRef.current?.speed ?? 2
                const delta = (speed * 60 * elapsed) / 1000

                const { pos: posX, hit: hitX } = updatePosition(
                    ctr.clientWidth,
                    delta,
                    el.clientWidth,
                    animationState.current.positionX,
                    'isPosXIncrement'
                )
                const { pos: posY, hit: hitY } = updatePosition(
                    ctr.clientHeight,
                    delta,
                    el.clientHeight,
                    animationState.current.positionY,
                    'isPosYIncrement'
                )

                if (hitX && hitY) {
                    optionsRef.current?.onCornerHit?.()
                }

                el.style.transform = `translate3d(${posX}px, ${posY}px, 0)`
                animationState.current.positionX = posX
                animationState.current.positionY = posY
            }

            animationState.current.animationFrameId = requestAnimationFrame(animate)
        }

        animateFnRef.current = animate

        if (element && container) {
            element.style.willChange = 'transform'
            element.style.userSelect = 'none'

            const maxX = Math.max(0, container.clientWidth - element.clientWidth)
            const maxY = Math.max(0, container.clientHeight - element.clientHeight)
            animationState.current.positionX = Math.random() * maxX
            animationState.current.positionY = Math.random() * maxY

            if (!optionsRef.current?.paused) {
                animationState.current.animationFrameId = requestAnimationFrame(animate)
            }
        }

        return () => {
            cancelAnimationFrame(animationState.current.animationFrameId)
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [])

    useEffect(() => {
        if (options?.paused) {
            cancelAnimationFrame(animationState.current.animationFrameId)
            animationState.current.animationFrameId = 0
            animationState.current.lastTimestamp = 0
        } else if (animateFnRef.current && !animationState.current.animationFrameId) {
            animationState.current.animationFrameId = requestAnimationFrame(animateFnRef.current)
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [options?.paused])

    return { containerRef, elementRef, impactCount }
}

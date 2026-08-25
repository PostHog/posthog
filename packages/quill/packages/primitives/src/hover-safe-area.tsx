import './hover-safe-area.css'

import * as React from 'react'

type HoverSafeAreaSide = 'top' | 'right' | 'bottom' | 'left'
type HoverSafeAreaPoint = { x: number; y: number }

type HoverSafeAreaProps = {
    anchorRef: React.RefObject<Element | null>
    floatingRef: React.RefObject<HTMLElement | null>
}

function initialPointer(rect: DOMRect, side: HoverSafeAreaSide): HoverSafeAreaPoint {
    if (side === 'top') {
        return { x: rect.left + rect.width / 2, y: rect.top }
    }
    if (side === 'right') {
        return { x: rect.right, y: rect.top + rect.height / 2 }
    }
    if (side === 'bottom') {
        return { x: rect.left + rect.width / 2, y: rect.bottom }
    }
    return { x: rect.left, y: rect.top + rect.height / 2 }
}

function pointerAtAnchorEdge(pointer: HoverSafeAreaPoint, rect: DOMRect, side: HoverSafeAreaSide): HoverSafeAreaPoint {
    if (side === 'top') {
        return { x: Math.min(Math.max(pointer.x, rect.left), rect.right), y: rect.top }
    }
    if (side === 'right') {
        return { x: rect.right, y: Math.min(Math.max(pointer.y, rect.top), rect.bottom) }
    }
    if (side === 'bottom') {
        return { x: Math.min(Math.max(pointer.x, rect.left), rect.right), y: rect.bottom }
    }
    return { x: rect.left, y: Math.min(Math.max(pointer.y, rect.top), rect.bottom) }
}

function inferSide(anchorRect: DOMRect, floatingRect: DOMRect): HoverSafeAreaSide {
    const gaps: Record<HoverSafeAreaSide, number> = {
        top: Math.abs(anchorRect.top - floatingRect.bottom),
        right: Math.abs(floatingRect.left - anchorRect.right),
        bottom: Math.abs(floatingRect.top - anchorRect.bottom),
        left: Math.abs(anchorRect.left - floatingRect.right),
    }

    return (Object.entries(gaps) as Array<[HoverSafeAreaSide, number]>).reduce((closest, candidate) =>
        candidate[1] < closest[1] ? candidate : closest
    )[0]
}

function safeAreaClipPath(pointer: HoverSafeAreaPoint, floatingRect: DOMRect, side: HoverSafeAreaSide): string {
    if (side === 'top') {
        return `polygon(${pointer.x}px ${pointer.y}px, ${floatingRect.left}px ${floatingRect.bottom}px, ${floatingRect.right}px ${floatingRect.bottom}px)`
    }
    if (side === 'right') {
        return `polygon(${pointer.x}px ${pointer.y}px, ${floatingRect.left}px ${floatingRect.top}px, ${floatingRect.left}px ${floatingRect.bottom}px)`
    }
    if (side === 'bottom') {
        return `polygon(${pointer.x}px ${pointer.y}px, ${floatingRect.right}px ${floatingRect.top}px, ${floatingRect.left}px ${floatingRect.top}px)`
    }
    return `polygon(${pointer.x}px ${pointer.y}px, ${floatingRect.right}px ${floatingRect.bottom}px, ${floatingRect.right}px ${floatingRect.top}px)`
}

function HoverSafeArea({ anchorRef, floatingRef }: HoverSafeAreaProps): React.ReactElement {
    const safeAreaRef = React.useRef<HTMLDivElement | null>(null)
    const pointerRef = React.useRef<HoverSafeAreaPoint | null>(null)

    const updateSafeArea = React.useCallback((): void => {
        const safeArea = safeAreaRef.current
        const anchor = anchorRef.current
        const floating = floatingRef.current
        if (!safeArea || !anchor || !floating || floating.hidden || floating.hasAttribute('data-closed')) {
            safeArea?.removeAttribute('data-ready')
            return
        }

        const anchorRect = anchor.getBoundingClientRect()
        const floatingRect = floating.getBoundingClientRect()
        if (
            anchorRect.width === 0 ||
            anchorRect.height === 0 ||
            floatingRect.width === 0 ||
            floatingRect.height === 0
        ) {
            safeArea.removeAttribute('data-ready')
            return
        }

        const dataSide = floating.getAttribute('data-side')
        const side =
            dataSide === 'top' || dataSide === 'right' || dataSide === 'bottom' || dataSide === 'left'
                ? dataSide
                : inferSide(anchorRect, floatingRect)
        const pointer = pointerRef.current
            ? pointerAtAnchorEdge(pointerRef.current, anchorRect, side)
            : initialPointer(anchorRect, side)

        safeArea.style.clipPath = safeAreaClipPath(pointer, floatingRect, side)
        safeArea.setAttribute('data-ready', '')
    }, [anchorRef, floatingRef])

    React.useEffect(() => {
        const anchor = anchorRef.current
        const floating = floatingRef.current
        pointerRef.current = null
        if (!anchor || !floating) {
            return
        }

        const handlePointerMove = (event: PointerEvent): void => {
            if (event.target instanceof Node && anchor.contains(event.target)) {
                pointerRef.current = { x: event.clientX, y: event.clientY }
                updateSafeArea()
            }
        }
        const observer = new ResizeObserver(updateSafeArea)
        const mutationObserver = new MutationObserver(updateSafeArea)

        updateSafeArea()
        observer.observe(anchor)
        observer.observe(floating)
        mutationObserver.observe(floating, {
            attributes: true,
            attributeFilter: ['data-closed', 'data-open', 'data-side', 'hidden'],
        })
        document.addEventListener('pointermove', handlePointerMove, { capture: true, passive: true })
        document.addEventListener('scroll', updateSafeArea, true)
        window.addEventListener('resize', updateSafeArea)

        return () => {
            observer.disconnect()
            mutationObserver.disconnect()
            document.removeEventListener('pointermove', handlePointerMove, true)
            document.removeEventListener('scroll', updateSafeArea, true)
            window.removeEventListener('resize', updateSafeArea)
        }
    }, [anchorRef, floatingRef, updateSafeArea])

    return <div ref={safeAreaRef} data-slot="hover-safe-area" className="quill-hover-safe-area" aria-hidden />
}

export { HoverSafeArea }
export type { HoverSafeAreaProps }

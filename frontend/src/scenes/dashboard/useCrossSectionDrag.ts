import { useCallback, useEffect, useRef, useState } from 'react'

import type { DashboardSection } from './dashboardLogic'

export type DashboardDropTarget = { type: 'section'; sectionKey: string } | { type: 'gap'; position: number } | null

interface UseCrossSectionDragProps {
    sections: DashboardSection[]
    disabled: boolean
    onDrop: (tileId: number, target: Exclude<DashboardDropTarget, null>, event: MouseEvent) => void
}

export function useCrossSectionDrag({ sections, disabled, onDrop }: UseCrossSectionDragProps): {
    registerSection: (sectionKey: string, element: HTMLElement | null) => void
    dropTarget: DashboardDropTarget
    startDrag: (tileId: number, sectionKey: string) => void
    updateDrag: (event: MouseEvent) => void
    finishDrag: (event: MouseEvent) => boolean
} {
    const sectionElements = useRef(new Map<string, HTMLElement>())
    const sectionRects = useRef(new Map<string, DOMRect>())
    const draggedTile = useRef<{ tileId: number; sectionKey: string } | null>(null)
    const frame = useRef<number | null>(null)
    const latestEvent = useRef<MouseEvent | null>(null)
    const currentTarget = useRef<DashboardDropTarget>(null)
    const [dropTarget, setDropTarget] = useState<DashboardDropTarget>(null)

    const measure = useCallback((): void => {
        sectionRects.current = new Map(
            [...sectionElements.current].map(([sectionKey, element]) => [sectionKey, element.getBoundingClientRect()])
        )
    }, [])

    useEffect(() => {
        if (!draggedTile.current) {
            return
        }
        window.addEventListener('scroll', measure, true)
        return () => window.removeEventListener('scroll', measure, true)
    }, [dropTarget, measure])

    const registerSection = useCallback((sectionKey: string, element: HTMLElement | null): void => {
        if (element) {
            sectionElements.current.set(sectionKey, element)
        } else {
            sectionElements.current.delete(sectionKey)
        }
    }, [])

    const startDrag = useCallback(
        (tileId: number, sectionKey: string): void => {
            if (disabled) {
                return
            }
            draggedTile.current = { tileId, sectionKey }
            measure()
        },
        [disabled, measure]
    )

    const resolveTarget = useCallback(
        (event: MouseEvent): DashboardDropTarget => {
            const orderedRects = sections
                .map((section, position) => ({ section, position, rect: sectionRects.current.get(section.key) }))
                .filter((entry): entry is typeof entry & { rect: DOMRect } => !!entry.rect)
            for (const { section, rect } of orderedRects) {
                if (event.clientY >= rect.top && event.clientY <= rect.bottom) {
                    return { type: 'section', sectionKey: section.key }
                }
            }
            for (let position = 0; position <= orderedRects.length; position++) {
                const before = orderedRects[position - 1]?.rect.bottom ?? Number.NEGATIVE_INFINITY
                const after = orderedRects[position]?.rect.top ?? Number.POSITIVE_INFINITY
                if (event.clientY > before && event.clientY < after) {
                    return { type: 'gap', position }
                }
            }
            return null
        },
        [sections]
    )

    const updateDrag = useCallback(
        (event: MouseEvent): void => {
            if (!draggedTile.current) {
                return
            }
            latestEvent.current = event
            if (frame.current !== null) {
                return
            }
            frame.current = requestAnimationFrame(() => {
                frame.current = null
                const nextTarget = latestEvent.current ? resolveTarget(latestEvent.current) : null
                currentTarget.current = nextTarget
                setDropTarget(nextTarget)
            })
        },
        [resolveTarget]
    )

    const finishDrag = useCallback(
        (event: MouseEvent): boolean => {
            const dragged = draggedTile.current
            const target = currentTarget.current
            draggedTile.current = null
            currentTarget.current = null
            setDropTarget(null)
            if (!dragged || !target) {
                return false
            }
            if (target.type === 'section' && target.sectionKey === dragged.sectionKey) {
                return false
            }
            onDrop(dragged.tileId, target, event)
            return true
        },
        [onDrop]
    )

    return { registerSection, dropTarget, startDrag, updateDrag, finishDrag }
}

import { useCallback, useRef, useState } from 'react'

import type { DashboardSection } from './dashboardSections'

export type DashboardDropTarget = { type: 'section'; sectionKey: string } | { type: 'gap'; position: number } | null

type DragSession = { kind: 'tile'; tileId: number; sectionKey: string } | { kind: 'section'; groupId: string } | null

const SECTION_EDGE_PX = 8

interface UseCrossSectionDragProps {
    sections: DashboardSection[]
    disabled: boolean
    onTileDrop: (tileId: number, target: Exclude<DashboardDropTarget, null>, event: MouseEvent) => void
    onSectionDrop: (groupId: string, position: number) => void
}

export function useCrossSectionDrag({ sections, disabled, onTileDrop, onSectionDrop }: UseCrossSectionDragProps): {
    registerSection: (sectionKey: string, element: HTMLElement | null) => void
    dropTarget: DashboardDropTarget
    startTileDrag: (tileId: number, sectionKey: string) => void
    startSectionDrag: (groupId: string, event: PointerEvent) => void
    updateDrag: (event: MouseEvent) => void
    finishDrag: (event: MouseEvent) => boolean
} {
    const sectionElements = useRef(new Map<string, HTMLElement>())
    const sectionRects = useRef(new Map<string, DOMRect>())
    const dragged = useRef<DragSession>(null)
    const frame = useRef<number | null>(null)
    const latestEvent = useRef<MouseEvent | null>(null)
    const currentTarget = useRef<DashboardDropTarget>(null)
    const sectionsRef = useRef(sections)
    const onTileDropRef = useRef(onTileDrop)
    const onSectionDropRef = useRef(onSectionDrop)
    const detachScroll = useRef<(() => void) | null>(null)
    const [dropTarget, setDropTarget] = useState<DashboardDropTarget>(null)

    sectionsRef.current = sections
    onTileDropRef.current = onTileDrop
    onSectionDropRef.current = onSectionDrop

    const measure = useCallback((): void => {
        sectionRects.current = new Map(
            [...sectionElements.current].map(([sectionKey, element]) => [sectionKey, element.getBoundingClientRect()])
        )
    }, [])

    const clearDrag = useCallback((): void => {
        dragged.current = null
        currentTarget.current = null
        latestEvent.current = null
        detachScroll.current?.()
        detachScroll.current = null
        if (frame.current !== null) {
            cancelAnimationFrame(frame.current)
            frame.current = null
        }
        setDropTarget(null)
    }, [])

    const registerSection = useCallback((sectionKey: string, element: HTMLElement | null): void => {
        if (element) {
            sectionElements.current.set(sectionKey, element)
        } else {
            sectionElements.current.delete(sectionKey)
        }
    }, [])

    const resolveTarget = useCallback((event: MouseEvent): DashboardDropTarget => {
        const orderedRects = sectionsRef.current
            .map((section, position) => ({ section, position, rect: sectionRects.current.get(section.key) }))
            .filter((entry): entry is typeof entry & { rect: DOMRect } => !!entry.rect)

        for (const { section, rect } of orderedRects) {
            if (event.clientY >= rect.top + SECTION_EDGE_PX && event.clientY <= rect.bottom - SECTION_EDGE_PX) {
                return { type: 'section', sectionKey: section.key }
            }
        }

        for (let position = 0; position <= orderedRects.length; position++) {
            const before = (orderedRects[position - 1]?.rect.bottom ?? Number.NEGATIVE_INFINITY) - SECTION_EDGE_PX
            const after = (orderedRects[position]?.rect.top ?? Number.POSITIVE_INFINITY) + SECTION_EDGE_PX
            if (event.clientY >= before && event.clientY <= after) {
                return { type: 'gap', position }
            }
        }
        return null
    }, [])

    const updateDrag = useCallback(
        (event: MouseEvent): void => {
            if (!dragged.current) {
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
            const session = dragged.current
            const target = currentTarget.current ?? resolveTarget(event)
            clearDrag()
            if (!session || !target) {
                return false
            }
            if (session.kind === 'tile') {
                if (target.type === 'section' && target.sectionKey === session.sectionKey) {
                    return false
                }
                onTileDropRef.current(session.tileId, target, event)
                return true
            }
            const position =
                target.type === 'gap'
                    ? target.position
                    : sectionsRef.current.findIndex((section) => section.key === target.sectionKey)
            if (position < 0) {
                return false
            }
            onSectionDropRef.current(session.groupId, position)
            return true
        },
        [clearDrag, resolveTarget]
    )

    const attachScrollMeasure = useCallback((): void => {
        detachScroll.current?.()
        const onScroll = (): void => {
            measure()
            if (!latestEvent.current) {
                return
            }
            const nextTarget = resolveTarget(latestEvent.current)
            currentTarget.current = nextTarget
            setDropTarget(nextTarget)
        }
        window.addEventListener('scroll', onScroll, true)
        detachScroll.current = () => window.removeEventListener('scroll', onScroll, true)
    }, [measure, resolveTarget])

    const startTileDrag = useCallback(
        (tileId: number, sectionKey: string): void => {
            if (disabled) {
                return
            }
            dragged.current = { kind: 'tile', tileId, sectionKey }
            measure()
            attachScrollMeasure()
        },
        [attachScrollMeasure, disabled, measure]
    )

    const startSectionDrag = useCallback(
        (groupId: string, event: PointerEvent): void => {
            if (disabled) {
                return
            }
            dragged.current = { kind: 'section', groupId }
            measure()
            attachScrollMeasure()
            const handleMove = (moveEvent: PointerEvent): void => {
                updateDrag(moveEvent)
            }
            const handleUp = (upEvent: PointerEvent): void => {
                window.removeEventListener('pointermove', handleMove)
                window.removeEventListener('pointerup', handleUp)
                finishDrag(upEvent)
            }
            window.addEventListener('pointermove', handleMove)
            window.addEventListener('pointerup', handleUp)
            updateDrag(event)
        },
        [attachScrollMeasure, disabled, finishDrag, measure, updateDrag]
    )

    return { registerSection, dropTarget, startTileDrag, startSectionDrag, updateDrag, finishDrag }
}

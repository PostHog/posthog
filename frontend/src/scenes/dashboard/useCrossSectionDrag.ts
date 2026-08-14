import { useCallback, useEffect, useRef, useState } from 'react'

import type { DashboardSection } from './dashboardSections'

export type DashboardDropTarget =
    | { type: 'section'; sectionKey: string; position: number; after: boolean }
    | { type: 'gap'; position: number }
    | null

type DragSession = { kind: 'tile'; tileId: number; sectionKey: string } | { kind: 'section'; groupId: string } | null

export interface DashboardTileDropLayout {
    x: number
    y: number
    w: number
    h: number
}

export interface DashboardSectionDragPreview {
    groupId: string
    height: number
    left: number
    top: number
    width: number
}

const SECTION_EDGE_PX = 32
const SECTION_TILE_DROP_EDGE_PX = 96

function dropTargetsEqual(first: DashboardDropTarget, second: DashboardDropTarget): boolean {
    if (!first || !second) {
        return first === second
    }
    if (first.type !== second.type) {
        return false
    }
    if (first.type === 'gap' && second.type === 'gap') {
        return first.position === second.position
    }
    if (first.type === 'gap' || second.type === 'gap') {
        return false
    }
    return first.sectionKey === second.sectionKey && first.position === second.position && first.after === second.after
}

interface UseCrossSectionDragProps {
    sections: DashboardSection[]
    disabled: boolean
    onTileDrop: (
        tileId: number,
        target: Exclude<DashboardDropTarget, null>,
        event: MouseEvent,
        layout: DashboardTileDropLayout | null,
        targetRect: DOMRect | null
    ) => void
    onSectionDrop: (groupId: string, position: number) => void
}

export function useCrossSectionDrag({ sections, disabled, onTileDrop, onSectionDrop }: UseCrossSectionDragProps): {
    registerSection: (sectionKey: string, element: HTMLElement | null) => void
    registerSectionDragPreview: (element: HTMLElement | null) => void
    draggedGroupId: string | null
    sectionDragPreview: DashboardSectionDragPreview | null
    dropTarget: DashboardDropTarget
    startTileDrag: (tileId: number, sectionKey: string) => void
    startSectionDrag: (groupId: string, event: PointerEvent, previewHeight: number) => void
    updateDrag: (event: MouseEvent) => void
    finishDrag: (event: MouseEvent, layout?: DashboardTileDropLayout | null) => boolean
} {
    const sectionElements = useRef(new Map<string, HTMLElement>())
    const sectionRects = useRef(new Map<string, DOMRect>())
    const sectionDragBaseRects = useRef(new Map<string, DOMRect>())
    const sectionDragScrollTop = useRef(0)
    const scrollContainer = useRef<HTMLElement | null>(null)
    const sectionDragStartY = useRef<number | null>(null)
    const sectionDragPointerOffset = useRef<{ x: number; y: number } | null>(null)
    const dragged = useRef<DragSession>(null)
    const frame = useRef<number | null>(null)
    const sectionCollapseFrame = useRef<number | null>(null)
    const latestEvent = useRef<MouseEvent | null>(null)
    const currentTarget = useRef<DashboardDropTarget>(null)
    const sectionsRef = useRef(sections)
    const onTileDropRef = useRef(onTileDrop)
    const onSectionDropRef = useRef(onSectionDrop)
    const detachScroll = useRef<(() => void) | null>(null)
    const detachPointerListeners = useRef<(() => void) | null>(null)
    const resizeObserver = useRef<ResizeObserver | null>(null)
    const needsMeasurement = useRef(false)
    const sectionDragPreviewElement = useRef<HTMLElement | null>(null)
    const [dropTarget, setDropTarget] = useState<DashboardDropTarget>(null)
    const [draggedGroupId, setDraggedGroupId] = useState<string | null>(null)
    const [sectionDragPreview, setSectionDragPreview] = useState<DashboardSectionDragPreview | null>(null)

    useEffect(() => {
        sectionsRef.current = sections
        onTileDropRef.current = onTileDrop
        onSectionDropRef.current = onSectionDrop
    }, [onSectionDrop, onTileDrop, sections])

    const measure = useCallback((): void => {
        sectionRects.current = new Map(
            [...sectionElements.current].map(([sectionKey, element]) => [sectionKey, element.getBoundingClientRect()])
        )
        sectionDragBaseRects.current = new Map(sectionRects.current)
        sectionDragScrollTop.current = scrollContainer.current?.scrollTop ?? 0
        needsMeasurement.current = false
    }, [])

    const getSectionRect = useCallback((sectionKey: string): DOMRect | undefined => {
        const baseRect = sectionDragBaseRects.current.get(sectionKey)
        if (!baseRect) {
            return sectionRects.current.get(sectionKey)
        }
        const scrollTop = scrollContainer.current?.scrollTop ?? 0
        const scrollDelta = scrollTop - sectionDragScrollTop.current
        return {
            ...baseRect,
            top: baseRect.top - scrollDelta,
            bottom: baseRect.bottom - scrollDelta,
        } as DOMRect
    }, [])

    const clearDrag = useCallback((): void => {
        dragged.current = null
        sectionDragBaseRects.current = new Map()
        sectionDragStartY.current = null
        sectionDragPointerOffset.current = null
        currentTarget.current = null
        latestEvent.current = null
        detachScroll.current?.()
        detachScroll.current = null
        detachPointerListeners.current?.()
        detachPointerListeners.current = null
        resizeObserver.current?.disconnect()
        resizeObserver.current = null
        scrollContainer.current = null
        if (frame.current !== null) {
            cancelAnimationFrame(frame.current)
            frame.current = null
        }
        if (sectionCollapseFrame.current !== null) {
            cancelAnimationFrame(sectionCollapseFrame.current)
            sectionCollapseFrame.current = null
        }
        setDropTarget(null)
        setDraggedGroupId(null)
        setSectionDragPreview(null)
    }, [])

    const registerSection = useCallback((sectionKey: string, element: HTMLElement | null): void => {
        if (element) {
            sectionElements.current.set(sectionKey, element)
        } else {
            sectionElements.current.delete(sectionKey)
        }
    }, [])

    const registerSectionDragPreview = useCallback((element: HTMLElement | null): void => {
        sectionDragPreviewElement.current = element
    }, [])

    useEffect(
        () => () => {
            detachScroll.current?.()
            detachPointerListeners.current?.()
            resizeObserver.current?.disconnect()
            if (frame.current !== null) {
                cancelAnimationFrame(frame.current)
            }
            if (sectionCollapseFrame.current !== null) {
                cancelAnimationFrame(sectionCollapseFrame.current)
            }
        },
        []
    )

    const resolveTarget = useCallback(
        (event: MouseEvent): DashboardDropTarget => {
            const orderedRects = sectionsRef.current
                .map((section, position) => ({ section, position, rect: getSectionRect(section.key) }))
                .filter((entry): entry is typeof entry & { rect: DOMRect } => !!entry.rect)
            const draggedSession = dragged.current
            const draggedGroupId = draggedSession?.kind === 'section' ? draggedSession.groupId : null
            const draggedGroupPosition = draggedGroupId
                ? orderedRects.findIndex((entry) => entry.section.group?.id === draggedGroupId)
                : -1
            const sectionIsMovingUp =
                draggedGroupId !== null &&
                sectionDragStartY.current !== null &&
                event.clientY < sectionDragStartY.current
            const edgeForSection = (rect: DOMRect): number =>
                draggedGroupId ? SECTION_EDGE_PX : Math.min(SECTION_TILE_DROP_EDGE_PX, rect.height / 4)

            for (const { section, position, rect } of orderedRects) {
                const sectionDrag = draggedGroupId !== null
                const sectionEdge = edgeForSection(rect)
                const isInsideSection = sectionDrag
                    ? event.clientY >= rect.top && event.clientY <= rect.bottom
                    : event.clientY >= rect.top + sectionEdge && event.clientY <= rect.bottom - sectionEdge
                if (isInsideSection) {
                    if (position === draggedGroupPosition) {
                        return null
                    }
                    return {
                        type: 'section',
                        sectionKey: section.key,
                        position,
                        after: !sectionIsMovingUp,
                    }
                }
            }

            for (let position = 0; position <= orderedRects.length; position++) {
                const previousRect = orderedRects[position - 1]?.rect
                const nextRect = orderedRects[position]?.rect
                const before = previousRect
                    ? previousRect.bottom - edgeForSection(previousRect)
                    : Number.NEGATIVE_INFINITY
                const after = nextRect ? nextRect.top + edgeForSection(nextRect) : Number.POSITIVE_INFINITY
                if (event.clientY >= before && event.clientY <= after) {
                    if (position === draggedGroupPosition || position === draggedGroupPosition + 1) {
                        return null
                    }
                    return { type: 'gap', position }
                }
            }
            return null
        },
        [getSectionRect]
    )

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
                if (needsMeasurement.current) {
                    measure()
                }
                if (dragged.current?.kind === 'section') {
                    const session = dragged.current
                    const offset = sectionDragPointerOffset.current
                    const rect = session?.kind === 'section' ? sectionDragBaseRects.current.get(session.groupId) : null
                    if (session?.kind === 'section' && offset && rect) {
                        const x = latestEvent.current!.clientX - offset.x - rect.left
                        const y = latestEvent.current!.clientY - offset.y - rect.top
                        sectionDragPreviewElement.current?.style.setProperty(
                            'transform',
                            `translate3d(${x}px, ${y}px, 0)`
                        )
                    }
                }
                const nextTarget = latestEvent.current ? resolveTarget(latestEvent.current) : null
                if (dropTargetsEqual(currentTarget.current, nextTarget)) {
                    return
                }
                currentTarget.current = nextTarget
                setDropTarget(nextTarget)
            })
        },
        [measure, resolveTarget]
    )

    const finishDrag = useCallback(
        (event: MouseEvent, layout: DashboardTileDropLayout | null = null): boolean => {
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
                const targetRect =
                    target.type === 'section' ? (sectionRects.current.get(target.sectionKey) ?? null) : null
                onTileDropRef.current(session.tileId, target, event, layout, targetRect)
                return true
            }
            const position = target.type === 'gap' ? target.position : target.position + Number(target.after)
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
            if (!latestEvent.current) {
                return
            }
            const nextTarget = resolveTarget(latestEvent.current)
            if (dropTargetsEqual(currentTarget.current, nextTarget)) {
                return
            }
            currentTarget.current = nextTarget
            setDropTarget(nextTarget)
        }
        window.addEventListener('scroll', onScroll, true)
        detachScroll.current = () => window.removeEventListener('scroll', onScroll, true)
    }, [resolveTarget])

    const startTileDrag = useCallback(
        (tileId: number, sectionKey: string): void => {
            if (disabled) {
                return
            }
            dragged.current = { kind: 'tile', tileId, sectionKey }
            scrollContainer.current = document.getElementById('main-content')
            measure()
            resizeObserver.current = new ResizeObserver(() => {
                needsMeasurement.current = true
            })
            sectionElements.current.forEach((element) => resizeObserver.current?.observe(element))
            attachScrollMeasure()
        },
        [attachScrollMeasure, disabled, measure]
    )

    const startSectionDrag = useCallback(
        (groupId: string, event: PointerEvent, previewHeight: number): void => {
            if (disabled) {
                return
            }
            dragged.current = { kind: 'section', groupId }
            sectionDragStartY.current = event.clientY
            setDraggedGroupId(groupId)
            scrollContainer.current = document.getElementById('main-content')
            measure()
            const sourceSection = sectionsRef.current.find((section) => section.group?.id === groupId)
            const sourceRect = sourceSection ? sectionRects.current.get(sourceSection.key) : null
            if (sourceRect) {
                sectionDragPointerOffset.current = {
                    x: event.clientX - sourceRect.left,
                    y: event.clientY - sourceRect.top,
                }
                setSectionDragPreview({
                    groupId,
                    height: previewHeight,
                    left: sourceRect.left,
                    top: sourceRect.top,
                    width: sourceRect.width,
                })
            }
            attachScrollMeasure()
            sectionCollapseFrame.current = requestAnimationFrame(() => {
                sectionCollapseFrame.current = null
                if (dragged.current?.kind === 'section' && dragged.current.groupId === groupId) {
                    measure()
                }
            })
            const handleMove = (moveEvent: PointerEvent): void => {
                updateDrag(moveEvent)
            }
            const finish = (upEvent: PointerEvent): void => {
                finishDrag(upEvent)
            }
            window.addEventListener('pointermove', handleMove)
            window.addEventListener('pointerup', finish)
            window.addEventListener('pointercancel', finish)
            detachPointerListeners.current = () => {
                window.removeEventListener('pointermove', handleMove)
                window.removeEventListener('pointerup', finish)
                window.removeEventListener('pointercancel', finish)
            }
            updateDrag(event)
        },
        [attachScrollMeasure, disabled, finishDrag, measure, updateDrag]
    )

    return {
        registerSection,
        registerSectionDragPreview,
        dropTarget,
        draggedGroupId,
        sectionDragPreview,
        startTileDrag,
        startSectionDrag,
        updateDrag,
        finishDrag,
    }
}

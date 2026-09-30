import { useActions, useValues } from 'kea'
import { KeyboardEvent, PointerEvent, RefCallback, useLayoutEffect, useMemo, useRef, useState } from 'react'

import {
    PreferredTodaySectionHeights,
    TODAY_SECTION_HEADER_HEIGHT,
    TodaySectionHeights,
    layoutTodaySections,
    resizeTodaySections,
} from './todaySectionLayout'
import { TodayWorkSectionId, todaySpacesLogic } from './todaySpacesLogic'

const KEYBOARD_STEP = 16

type MeasuredKey = TodayWorkSectionId | 'area'

export interface TodaySectionResizer {
    onPointerDown: (event: PointerEvent<HTMLElement>) => void
    onPointerMove: (event: PointerEvent<HTMLElement>) => void
    onPointerUp: (event: PointerEvent<HTMLElement>) => void
    onPointerCancel: () => void
    onKeyDown: (event: KeyboardEvent<HTMLElement>) => void
    onDoubleClick: () => void
}

interface Drag {
    lower: TodayWorkSectionId
    startY: number
    start: TodaySectionHeights
    preferred: PreferredTodaySectionHeights
}

function useMeasuredHeights(): {
    measuredHeights: Partial<Record<MeasuredKey, number>>
    measureRefs: Record<MeasuredKey, RefCallback<HTMLElement>>
} {
    const [measuredHeights, setMeasuredHeights] = useState<Partial<Record<MeasuredKey, number>>>({})
    const elements = useRef(new Map<MeasuredKey, HTMLElement>())
    const observer = useRef<ResizeObserver | null>(null)

    const measure = useMemo(
        () => (): void =>
            setMeasuredHeights((previous) => {
                const next = { ...previous }
                for (const [key, element] of elements.current) {
                    next[key] = key === 'area' ? element.clientHeight : element.offsetHeight
                }
                return Object.entries(next).every(([key, value]) => previous[key as MeasuredKey] === value)
                    ? previous
                    : next
            }),
        []
    )

    useLayoutEffect(() => {
        const resizeObserver = new ResizeObserver(measure)
        observer.current = resizeObserver
        for (const element of elements.current.values()) {
            resizeObserver.observe(element)
        }
        measure()
        return () => {
            resizeObserver.disconnect()
            observer.current = null
        }
    }, [measure])

    const measureRefs = useMemo(() => {
        const ref =
            (key: MeasuredKey): RefCallback<HTMLElement> =>
            (element) => {
                const previous = elements.current.get(key)
                if (previous && previous !== element) {
                    observer.current?.unobserve(previous)
                    elements.current.delete(key)
                }
                if (element) {
                    elements.current.set(key, element)
                    observer.current?.observe(element)
                    measure()
                }
            }
        return { area: ref('area'), pinned: ref('pinned'), recent: ref('recent'), spaces: ref('spaces') }
    }, [measure])

    return { measuredHeights, measureRefs }
}

export function useTodaySectionLayout(sections: readonly { id: TodayWorkSectionId; open: boolean }[]): {
    measureRefs: Record<MeasuredKey, RefCallback<HTMLElement>>
    heights: TodaySectionHeights
    measured: boolean
    dragging: TodayWorkSectionId | null
    resizer: (upper: TodayWorkSectionId, lower: TodayWorkSectionId) => TodaySectionResizer
} {
    const { sectionHeights } = useValues(todaySpacesLogic)
    const { setSectionHeights, resetSectionPair } = useActions(todaySpacesLogic)
    const { measuredHeights, measureRefs } = useMeasuredHeights()
    const [drag, setDrag] = useState<Drag | null>(null)

    const areaHeight = measuredHeights.area ?? 0
    const inputs = sections.map((section) => ({ ...section, contentHeight: measuredHeights[section.id] ?? 0 }))
    const heights = layoutTodaySections(
        inputs,
        areaHeight - TODAY_SECTION_HEADER_HEIGHT * sections.length,
        drag?.preferred ?? sectionHeights
    )
    const measured =
        areaHeight > 0 && sections.every((section) => !section.open || measuredHeights[section.id] !== undefined)

    const resizer = (upper: TodayWorkSectionId, lower: TodayWorkSectionId): TodaySectionResizer => {
        const resize = (delta: number, base: TodaySectionHeights): PreferredTodaySectionHeights =>
            resizeTodaySections({ sections: inputs, heights: base, upper, lower, delta, preferred: sectionHeights })
        const active = drag?.lower === lower ? drag : null
        return {
            onPointerDown: (event) => {
                if (event.button !== 0) {
                    return
                }
                event.preventDefault()
                event.currentTarget.setPointerCapture(event.pointerId)
                setDrag({ lower, startY: event.clientY, start: heights, preferred: sectionHeights })
            },
            onPointerMove: (event) => {
                if (!active) {
                    return
                }
                setDrag({ ...active, preferred: resize(event.clientY - active.startY, active.start) })
            },
            onPointerUp: (event) => {
                if (!active) {
                    return
                }
                if (event.clientY !== active.startY) {
                    setSectionHeights(resize(event.clientY - active.startY, active.start))
                }
                setDrag(null)
            },
            onPointerCancel: () => setDrag(null),
            onKeyDown: (event) => {
                if (event.key !== 'ArrowUp' && event.key !== 'ArrowDown') {
                    return
                }
                event.preventDefault()
                setSectionHeights(resize(event.key === 'ArrowUp' ? -KEYBOARD_STEP : KEYBOARD_STEP, heights))
            },
            onDoubleClick: () => resetSectionPair(upper, lower),
        }
    }

    return { measureRefs, heights, measured, dragging: drag?.lower ?? null, resizer }
}
